"""Security regression contract for v0.3.1 local-only POC."""
import asyncio
import io
import secrets
import time
from fastapi.testclient import TestClient
from app.main import app
from app import oauth_routes, siwc
from app.local_security import LocalSecurity
from app.siwc_store import CredentialStore

HOST = "http://127.0.0.1:8000"

def local_client():
    return TestClient(app, base_url=HOST)

def admin_session(monkeypatch, tmp_path):
    sec = LocalSecurity(CredentialStore(tmp_path))
    key = sec.initialize()
    monkeypatch.setattr(oauth_routes, "security", sec)
    client = local_client()
    response = client.get("/settings")
    assert "Settings locked" in response.text
    csrf = response.text.split('name="csrf" value="')[1].split('"')[0]
    assert client.post("/auth/unlock", data={"csrf": csrf, "key": key}, follow_redirects=False).status_code == 303
    return sec, client, csrf

def test_unpaired_requests_rejected_before_image_processing(monkeypatch):
    from app import main
    def fail(*args, **kwargs): raise AssertionError("OCR must never be called")
    monkeypatch.setattr(main, "extract_regions", fail)
    client = local_client()
    for path in ("/api/v1/translate", "/api/v1/translate-rendered"):
        response = client.post(path, files={"file": ("a.png", b"not image", "image/png")})
        assert response.status_code == 401
    assert client.get("/api/v1/provider/status").status_code == 401

def test_untrusted_host_and_origin():
    client = local_client()
    assert client.post("/api/v1/translate", headers={"host": "attacker.test"}).status_code == 403
    assert client.post("/api/v1/translate", headers={"origin": "https://attacker.test"}).status_code == 403
    assert client.post("/api/v1/pair/redeem", json={"code": "fake"}, headers={"origin": "https://attacker.test"}).status_code == 403

def test_settings_require_admin_and_csrf(monkeypatch, tmp_path):
    sec = LocalSecurity(CredentialStore(tmp_path))
    key = sec.initialize()
    monkeypatch.setattr(oauth_routes, "security", sec)
    client = local_client()
    p = client.get("/settings")
    csrf = p.text.split('name="csrf" value="')[1].split('"')[0]
    assert client.get("/auth/models").status_code == 403
    assert client.post("/auth/start", data={"csrf": csrf}, follow_redirects=False).status_code == 403
    assert client.post("/auth/pair", data={"csrf": csrf}, follow_redirects=False).status_code == 403
    assert client.post("/auth/unlock", data={"csrf": "bad", "key": key}).status_code == 403
    assert client.post("/auth/unlock", data={"csrf": csrf, "key": key}, headers={"origin": "https://evil.test"}).status_code == 403
    assert client.post("/auth/unlock", data={"csrf": csrf, "key": key}, follow_redirects=False).status_code == 303
    assert client.post("/auth/pair", data={"csrf": "bad"}, follow_redirects=False).status_code == 403
    assert client.post("/auth/pair", data={"csrf": csrf}, follow_redirects=False).status_code == 200

def test_pairing_single_use_revocation_and_wrong_code(tmp_path):
    sec = LocalSecurity(CredentialStore(tmp_path))
    sec.initialize()
    code = sec.issue_pairing()
    assert not sec.verify_capability("Bearer " + code)
    try:
        sec.redeem("wrong")
        assert False
    except Exception: pass
    token = sec.redeem(code)
    assert sec.verify_capability("Bearer " + token)
    try:
        sec.redeem(code)
        assert False
    except Exception: pass
    sec.revoke()
    assert not sec.verify_capability("Bearer " + token)

def test_pairing_expired(tmp_path):
    sec = LocalSecurity(CredentialStore(tmp_path))
    sec.initialize()
    code = sec.issue_pairing()
    sec.store._write("extension-pairing.json", {"hash": sec.store._read("extension-pairing.json")["hash"], "expires": time.time()-1})
    from fastapi import HTTPException
    try:
        sec.redeem(code)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 403

def test_multiple_oauth_attempts_wrong_state_and_atomic_replay(tmp_path):
    auth = siwc.ChatGPTAuth(CredentialStore(tmp_path))
    auth.start(session_id="A")
    a = auth.pending.state
    auth.start(session_id="B")
    b = auth.pending.state
    assert a != b
    from pytest import raises
    with raises(siwc.AuthError):
        auth._consume_attempt("bogus", session_id="A")
    assert a in auth.attempts and b in auth.attempts
    with raises(siwc.AuthError):
        auth._consume_attempt(a, session_id="B")
    assert a in auth.attempts
    assert auth._consume_attempt(a, session_id="A").state == a
    with raises(siwc.AuthError):
        auth._consume_attempt(a, session_id="A")
    assert auth._consume_attempt(b, session_id="B").state == b

def test_oauth_bounded_storage_and_expiry(tmp_path):
    auth = siwc.ChatGPTAuth(CredentialStore(tmp_path))
    for _ in range(32): auth.start(session_id="A")
    from pytest import raises
    with raises(siwc.AuthError, match="Too many"): auth.start(session_id="A")
    expired = next(iter(auth.attempts))
    from dataclasses import replace
    auth.attempts[expired] = replace(auth.attempts[expired], expires_at=time.monotonic()-1)
    with raises(siwc.AuthError): auth._consume_attempt(expired, session_id="A")
    auth.start(session_id="A")


def test_settings_referrer_policy_allows_browser_origin_for_unlock(monkeypatch, tmp_path):
    """Settings form uses same-origin policy while keeping external POST origins denied."""
    sec = LocalSecurity(CredentialStore(tmp_path))
    key = sec.initialize()
    monkeypatch.setattr(oauth_routes, "security", sec)
    client = local_client()
    page = client.get("/settings")
    assert page.headers["referrer-policy"] == "same-origin"
    csrf = page.text.split('name="csrf" value="')[1].split('"')[0]
    # Standard same-origin form POST succeeds.
    response = client.post("/auth/unlock", data={"csrf": csrf, "key": key},
                           headers={"origin": HOST, "referer": HOST + "/settings"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    # Cross-site and opaque origins cannot unlock even with otherwise valid CSRF/key.
    for origin in ("null", "https://evil.example"):
        denied = client.post("/auth/unlock", data={"csrf": csrf, "key": key},
                             headers={"origin": origin}, follow_redirects=False)
        assert denied.status_code == 403


def test_external_top_level_navigation_to_settings_is_allowed():
    client = local_client()
    response = client.get("/settings", headers={
        "sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate",
        "sec-fetch-dest": "document", "referer": "https://chatgpt.com/"})
    assert response.status_code == 200
    assert "Settings" in response.text
    assert "no-store" in response.headers["cache-control"]


def test_cross_site_settings_subresource_and_mutations_are_denied():
    client = local_client()
    base = {"sec-fetch-site": "cross-site", "referer": "https://evil.example/"}
    assert client.get("/settings", headers={**base, "sec-fetch-mode": "cors",
                                             "sec-fetch-dest": "empty"}).status_code == 403
    assert client.get("/auth/models", headers={**base, "sec-fetch-mode": "navigate",
                                                "sec-fetch-dest": "document"}).status_code == 403  # no admin session
    assert client.post("/auth/unlock", data={"csrf": "fake", "key": "fake"},
                       headers={**base, "sec-fetch-mode": "navigate",
                                "sec-fetch-dest": "document"}).status_code == 403
    assert client.get("/settings", headers={**base, "host": "evil.example",
                                            "sec-fetch-mode": "navigate",
                                            "sec-fetch-dest": "document"}).status_code == 403


def test_owner_route_policy_matrix(monkeypatch, tmp_path):
    """Every owner route: top-level GET navigation vs cross-site mutation."""
    sec, client, csrf = admin_session(monkeypatch, tmp_path)
    headers_nav = {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate",
                   "sec-fetch-dest": "document", "referer": "https://chatgpt.com/"}
    # Authentication remains mandatory, but a top-level navigation may open an admin read.
    async def models(): return []
    monkeypatch.setattr(oauth_routes.auth, "models", models)
    assert client.get("/auth/models", headers=headers_nav).status_code == 200
    assert client.get("/settings", headers=headers_nav).status_code == 200
    assert client.get("/auth/models", headers={**headers_nav, "host": "evil.example"}).status_code == 403
    # A cross-site POST is never a permitted navigation, even with admin cookie and CSRF.
    for path in ("/auth/unlock", "/auth/start", "/auth/reconnect",
                 "/auth/model", "/auth/logout", "/auth/pair", "/auth/pair/revoke"):
        assert client.post(path, data={"csrf": csrf},
                           headers=headers_nav, follow_redirects=False).status_code == 403
        assert client.post(path, data={"csrf": csrf},
                           headers={"origin": "http://127.0.0.1:9000"},
                           follow_redirects=False).status_code == 403
        assert client.post(path, data={"csrf": csrf},
                           headers={"sec-fetch-site": "same-site"},
                           follow_redirects=False).status_code == 403
    # Non-navigation cross-site fetch cannot read the authenticated model list.
    assert client.get("/auth/models", headers={"sec-fetch-site": "cross-site",
                      "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"}).status_code == 403


def test_extension_apis_never_use_navigation_exemption():
    c = local_client()
    navigation = {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate",
                  "sec-fetch-dest": "document"}
    assert c.get("/api/v1/provider/status", headers=navigation).status_code == 403
    assert c.post("/api/v1/pair/redeem", json={"code": "invalid"},
                  headers=navigation).status_code == 403
    assert c.post("/api/v1/translate", headers=navigation).status_code == 403
    assert c.post("/api/v1/translate-rendered", headers=navigation).status_code == 403
