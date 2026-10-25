import asyncio
import json
import os
import stat
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import oauth_routes, siwc
from app.siwc_store import CredentialStore


def test_pkce_and_state(tmp_path):
    auth = siwc.ChatGPTAuth(CredentialStore(tmp_path))
    url = auth.start()
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["dynamic_agent_client"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"][0] == siwc.pkce_challenge(auth.pending.verifier)
    assert q["ext_agent_host_id"][0] == auth.store.host_id()
    with pytest.raises(siwc.AuthError):
        auth._consume_attempt("wrong")
    assert auth.pending is None


def test_host_id_and_permissions(tmp_path):
    store = CredentialStore(tmp_path)
    original = store.host_id()
    assert store.host_id() == original
    store.save({"client_id": "abc", "refresh_token": "SECRET"})
    mode = stat.S_IMODE((tmp_path / "credentials.json").stat().st_mode)
    assert mode == 0o600
    store.clear_tokens()
    assert store.load().get("refresh_token") is None


def test_scope_gate(tmp_path):
    auth = siwc.ChatGPTAuth(CredentialStore(tmp_path))
    auth.store.save({"access_token": "secret", "expires_at": time.time()+1000,"scopes":["openid"]})
    with pytest.raises(siwc.AuthError, match="permission"):
        asyncio.run(auth.access_token())


def test_models_filter(tmp_path):
    def mock(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200,json={"models":[
            {"visibility":"list","slug":"model-1","display_name":"Model 1"},
            {"visibility":"hidden","slug":"model-2"}]})
    auth = siwc.ChatGPTAuth(CredentialStore(tmp_path),transport=httpx.MockTransport(mock))
    auth.store.save({"access_token":"secret","refresh_token":"refresh","scopes":[siwc.PERMISSION],
                     "expires_at":time.time()+300})
    assert asyncio.run(auth.models()) == [{"slug":"model-1","display_name":"Model 1"}]


def test_stream_requires_completed(tmp_path):
    def mock(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["stream"] is True and body["store"] is False
        return httpx.Response(200, content='data: ' + json.dumps({"type": "response.output_text.delta", "delta": '{"translations":["สวัสดี"]}'}, ensure_ascii=False) + '\n\n')
    auth=siwc.ChatGPTAuth(CredentialStore(tmp_path),transport=httpx.MockTransport(mock))
    auth.store.save({"access_token":"x","scopes":[siwc.PERMISSION],"expires_at":time.time()+300,
                     "selected_model":"model-1"})
    with pytest.raises(siwc.AuthError,match="before completion"):
        asyncio.run(auth.infer("Hello"))


def test_callback_state_replay(tmp_path):
    auth=siwc.ChatGPTAuth(CredentialStore(tmp_path))
    auth.start()
    state=auth.pending.state
    with pytest.raises(siwc.AuthError):
        asyncio.run(auth.callback(None,state,None,"access_denied"))
    with pytest.raises(siwc.AuthError):
        asyncio.run(auth.callback("fake",state,None,None))


def test_csrf_and_origin():
    client=TestClient(app,base_url="http://127.0.0.1:8000")
    response=client.get("/settings")
    assert response.status_code==200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.post("/auth/start",data={"csrf":"invalid"},follow_redirects=False).status_code==403
    assert client.post("/auth/start",data={"csrf":"invalid"},headers={"origin":"https://evil.example"},follow_redirects=False).status_code==403
    assert client.get("/settings",headers={"host":"evil.example"}).status_code==403
    assert "access_token" not in client.get("/api/v1/provider/status").text


def test_chatgpt_translation_adapter(monkeypatch):
    from app import main
    async def fake(lines):
        assert lines == ["Hello"]
        return ["สวัสดี"]
    monkeypatch.setattr(main,"translate_chatgpt",fake)
    monkeypatch.setenv("TRANSLATOR_PROVIDER","chatgpt_oauth")
    assert asyncio.run(main.translate_texts(["Hello"])) == ["สวัสดี"]


def test_logout_bad_discovery_clears_tokens(tmp_path):
    def mock(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"revocation_endpoint": "https://attacker.example/revoke"})
        raise AssertionError("Must never post token to untrusted host")
    auth = siwc.ChatGPTAuth(CredentialStore(tmp_path), transport=httpx.MockTransport(mock))
    auth.store.save({"client_id":"oaiapp_demo","access_token":"secret",
                     "refresh_token":"sensitive-refresh","scopes":[siwc.PERMISSION]})
    result = asyncio.run(auth.logout())
    assert result["remote_revocation_confirmed"] is False
    assert "refresh_token" not in auth.store.load()


def test_settings_form_submits_valid_csrf_and_starts_oauth(monkeypatch):
    """Regression: the HTML must contain the actual CSRF token, not +csrf+."""
    from html.parser import HTMLParser
    from app import oauth_routes

    class FormInspector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.forms = {}
            self.action = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.action = attrs.get("action")
            elif tag == "input" and self.action and attrs.get("name") == "csrf":
                self.forms[self.action] = attrs.get("value")

        def handle_endtag(self, tag):
            if tag == "form":
                self.action = None

    client = TestClient(app, base_url="http://127.0.0.1:8000")
    page = client.get("/settings")
    assert page.status_code == 200
    inspector = FormInspector()
    inspector.feed(page.text)
    assert set(inspector.forms) == {"/auth/start", "/auth/reconnect", "/auth/model", "/auth/logout"}
    tokens = set(inspector.forms.values())
    assert len(tokens) == 1
    token = tokens.pop()
    assert token and token != "+csrf+" and len(token) > 30

    monkeypatch.setattr(oauth_routes.auth, "start", lambda reconnect=False: "https://auth.openai.com/test")
    response = client.post("/auth/start", data={"csrf": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "https://auth.openai.com/test"

    rejected = client.post("/auth/start", data={"csrf": "invalid"}, follow_redirects=False)
    assert rejected.status_code == 403


def test_oauth_csp_allows_only_openai_redirect_origin():
    """Chrome rechecks form-action after the POST /auth/start 303 redirect."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    response = client.get("/settings")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "form-action 'self' https://auth.openai.com;" in csp
    assert "default-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action *" not in csp
    assert "http://auth.openai.com" not in csp
    assert "'unsafe-eval'" not in csp
