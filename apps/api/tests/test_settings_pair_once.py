"""Pair-once ownership, browser session handoff and Settings UX regressions."""
import hashlib
import re
import time

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import local_security, oauth_routes, siwc
from app.local_security import LocalSecurity
from app.main import app
from app.siwc_store import CredentialStore

HOST = "http://127.0.0.1:8000"
ORIGIN = "chrome-extension://" + "a" * 32
OTHER_ORIGIN = "chrome-extension://" + "b" * 32


@pytest.fixture
def setup(monkeypatch, tmp_path):
    sec = LocalSecurity(CredentialStore(tmp_path / "local"))
    def transport(request):
        assert request.url.path == "/v1/models", "Settings must never submit inference"
        return httpx.Response(200, json={"models": [
            {"visibility": "list", "slug": "vision-test", "display_name": "Test model"},
            {"visibility": "hidden", "slug": "hidden-test"}]})
    account = siwc.ChatGPTAuth(CredentialStore(tmp_path / "account"), transport=httpx.MockTransport(transport))
    monkeypatch.setattr(oauth_routes, "security", sec)
    monkeypatch.setattr(local_security, "security", sec)
    monkeypatch.setattr(oauth_routes, "auth", account)
    monkeypatch.setattr(oauth_routes, "_sessions", {})
    monkeypatch.setattr(oauth_routes, "_settings_tickets", {})
    with TestClient(app, base_url=HOST) as client:
        yield sec, account, client


def connect(account, model=None):
    account.store.save({"access_token": "generated-test-access", "refresh_token": "generated-test-refresh",
                        "expires_at": time.time() + 3600, "scopes": [siwc.PERMISSION],
                        "email": "reader@example.invalid", "selected_model": model})


def pair(sec, client, *, management=True):
    code = sec.issue_pairing(manage_settings=management)
    response = client.post("/api/v1/pair/redeem", headers={"origin": ORIGIN},
                           json={"code": code, "allow_settings": True})
    assert response.status_code == 200
    return response.json()


def headers(credentials):
    return {"origin": ORIGIN, "authorization": "Bearer " + credentials["settings_token"]}


def ticket(client, credentials):
    response = client.post("/api/v1/settings/ticket", headers=headers(credentials))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()["ticket"]


def open_settings(client, credentials):
    value = ticket(client, credentials)
    response = client.post("/auth/extension-session", headers={"origin": ORIGIN},
                           data={"ticket": value}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    return client.get("/settings")


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text)[1]


def test_owner_cli_pair_needs_no_admin_key_and_remembers_separate_authority(setup):
    sec, account, client = setup
    assert not sec.initialized()
    credentials = pair(sec, client)
    assert set(credentials) == {"token", "settings_token"}
    assert credentials["token"] != credentials["settings_token"]
    assert sec.verify_capability("Bearer " + credentials["token"])
    assert not sec.verify_capability("Bearer " + credentials["settings_token"])
    assert not sec.settings_generation("Bearer " + credentials["token"])
    assert sec.settings_generation("Bearer " + credentials["settings_token"])
    persisted = (sec.store.directory / "extension-capability.json").read_text()
    assert all(secret not in persisted for secret in credentials.values())
    assert not sec.initialized()
    page = open_settings(client, credentials)
    assert "เชื่อมต่อ ChatGPT" in page.text
    assert 'name="key"' not in page.text
    assert all(secret not in page.text for secret in credentials.values())


def test_explicit_management_consent_required_without_consuming_code(setup):
    sec, _, client = setup
    code = sec.issue_pairing(manage_settings=True)
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}", code)
    denied = client.post("/api/v1/pair/redeem", json={"code": code})
    assert denied.status_code == 409
    assert not sec.current_generation()
    accepted = client.post("/api/v1/pair/redeem", json={"code": code.lower().replace("-", " "), "allow_settings": True})
    assert accepted.status_code == 200
    assert client.post("/api/v1/pair/redeem", json={"code": code, "allow_settings": True}).status_code == 403


def test_legacy_code_never_gets_management_scope_from_checkbox(setup):
    sec, _, client = setup
    credentials = pair(sec, client, management=False)
    assert set(credentials) == {"token"}
    denied = client.post("/api/v1/settings/ticket", headers={"origin": ORIGIN, "authorization": "Bearer " + credentials["token"]})
    assert denied.status_code == 401
    assert client.get("/api/v1/provider/status", headers={"authorization": "Bearer " + credentials["token"]}).status_code == 200


def test_pairing_code_expiry_and_rate_limit(setup, monkeypatch):
    sec, _, client = setup
    code = sec.issue_pairing(manage_settings=True)
    expires = sec.store._read("extension-pairing.json")["expires"]
    monkeypatch.setattr(local_security.time, "time", lambda: expires + 1)
    assert client.post("/api/v1/pair/redeem", json={"code": code, "allow_settings": True}).status_code == 403
    for _ in range(4):
        assert client.post("/api/v1/pair/redeem", json={"code": "invalid"}).status_code == 403
    assert client.post("/api/v1/pair/redeem", json={"code": code, "allow_settings": True}).status_code == 429


@pytest.mark.parametrize("origin", [None, "null", HOST, "https://evil.invalid", "http://127.0.0.1:9000", "chrome-extension://" + "z" * 32])
def test_management_requires_real_extension_origin_even_with_valid_credential(setup, origin):
    sec, _, client = setup
    credentials = pair(sec, client)
    request_headers = {"authorization": "Bearer " + credentials["settings_token"]}
    if origin is not None:
        request_headers["origin"] = origin
    assert client.get("/api/v1/settings/status", headers=request_headers).status_code == 403
    assert client.post("/api/v1/settings/ticket", headers=request_headers).status_code == 403
    value = ticket(client, credentials)
    assert client.post("/auth/extension-session", headers=request_headers, data={"ticket": value}, follow_redirects=False).status_code == 403


def test_ticket_origin_binding_single_use_and_session_csrf(setup):
    sec, _, client = setup
    credentials = pair(sec, client)
    value = ticket(client, credentials)
    key = hashlib.sha256(value.encode()).hexdigest()
    assert value not in str(oauth_routes._settings_tickets)
    assert client.post("/auth/extension-session", headers={"origin": OTHER_ORIGIN}, data={"ticket": value}).status_code == 403
    assert key in oauth_routes._settings_tickets
    response = client.post("/auth/extension-session", headers={"origin": ORIGIN}, data={"ticket": value}, follow_redirects=False)
    assert response.status_code == 303
    assert value not in response.headers["location"]
    assert key not in oauth_routes._settings_tickets
    assert client.post("/auth/extension-session", headers={"origin": ORIGIN}, data={"ticket": value}).status_code == 403
    page = client.get("/settings")
    assert client.post("/auth/start", data={"csrf": "invalid"}, follow_redirects=False).status_code == 403
    result = client.post("/auth/start", data={"csrf": csrf(page)}, headers={"origin": HOST}, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"].startswith("https://auth.openai.com/")
    assert client.post("/auth/logout", data={"csrf": csrf(page)}, headers={"origin": "https://evil.invalid"}).status_code == 403


def test_expired_ticket_rejected_and_pending_tickets_bounded(setup):
    sec, _, client = setup
    credentials = pair(sec, client)
    value = ticket(client, credentials)
    oauth_routes._settings_tickets[hashlib.sha256(value.encode()).hexdigest()]["expires"] = time.monotonic() - 1
    assert client.post("/auth/extension-session", headers={"origin": ORIGIN}, data={"ticket": value}).status_code == 403
    for _ in range(32):
        ticket(client, credentials)
    assert client.post("/api/v1/settings/ticket", headers=headers(credentials)).status_code == 429
    assert len(oauth_routes._settings_tickets) == 32


@pytest.mark.parametrize("operation", ["revoke", "repair"])
def test_revocation_invalidates_browser_sessions_tickets_and_old_credentials(setup, operation):
    sec, account, client = setup
    credentials = pair(sec, client)
    page = open_settings(client, credentials)
    value = ticket(client, credentials)
    if operation == "revoke":
        result = client.post("/api/v1/pair/revoke", headers={"origin": ORIGIN, "authorization": "Bearer " + credentials["token"]})
        assert result.status_code == 200
    else:
        pair(sec, client)
    assert client.get("/api/v1/settings/status", headers=headers(credentials)).status_code == 401
    assert client.post("/api/v1/settings/ticket", headers=headers(credentials)).status_code == 401
    assert client.post("/auth/extension-session", headers={"origin": ORIGIN}, data={"ticket": value}).status_code == 403
    for path in ["/auth/start", "/auth/reconnect", "/auth/model", "/auth/logout", "/auth/pair", "/auth/pair/revoke"]:
        assert client.post(path, data={"csrf": csrf(page)}, follow_redirects=False).status_code == 403
    assert client.get("/auth/models").status_code == 403
    callback = client.get("/auth/callback?error=access_denied")
    assert callback.status_code == 403
    assert callback.headers["referrer-policy"] == "no-referrer"
    assert "ยังไม่ได้อนุญาตการตั้งค่า" in client.get("/settings").text


def test_creating_new_code_preserves_existing_pairing_until_redemption(setup):
    sec, _, client = setup
    credentials = pair(sec, client)
    sec.issue_pairing(manage_settings=True)
    assert client.get("/api/v1/settings/status", headers=headers(credentials)).status_code == 200
    assert sec.verify_capability("Bearer " + credentials["token"])


def test_persisted_credentials_reopen_after_gateway_restart(setup, monkeypatch):
    sec, _, client = setup
    credentials = pair(sec, client)
    open_settings(client, credentials)
    restarted = LocalSecurity(sec.store)
    monkeypatch.setattr(oauth_routes, "security", restarted)
    monkeypatch.setattr(local_security, "security", restarted)
    monkeypatch.setattr(oauth_routes, "_sessions", {})
    monkeypatch.setattr(oauth_routes, "_settings_tickets", {})
    assert "ยังไม่ได้อนุญาตการตั้งค่า" in client.get("/settings").text
    assert "เชื่อมต่อ ChatGPT" in open_settings(client, credentials).text


def test_status_checks_do_not_consume_translation_budget(setup):
    sec, _, client = setup
    credentials = pair(sec, client)
    for _ in range(20):
        assert client.get("/api/v1/provider/status", headers={"origin": ORIGIN, "authorization": "Bearer " + credentials["token"]}).status_code == 200
        assert client.get("/api/v1/settings/status", headers=headers(credentials)).status_code == 200
    assert sec.requests == []
    assert sec.inflight == 0


def test_dropdown_uses_available_models_and_saves_with_csrf(setup):
    sec, account, client = setup
    connect(account)
    credentials = pair(sec, client)
    page = open_settings(client, credentials)
    assert '<select id="model" name="slug" required>' in page.text
    assert '<option value="vision-test">Test model</option>' in page.text
    assert "hidden-test" not in page.text
    response = client.post("/auth/model", data={"csrf": csrf(page), "slug": "vision-test"}, follow_redirects=False)
    assert response.status_code == 303
    assert account.status()["model"] == "vision-test"
    assert 'value="vision-test" selected' in client.get("/settings").text
    denied = client.post("/auth/model", data={"csrf": csrf(page), "slug": "not-in-catalog"})
    assert denied.status_code == 400
    assert "บันทึกโมเดลไม่สำเร็จ" in denied.text
    assert account.status()["model"] == "vision-test"


def test_model_catalog_failure_has_recovery_and_keeps_selection(setup, monkeypatch):
    sec, account, client = setup
    connect(account, "vision-test")
    async def unavailable():
        raise siwc.AuthError("generated provider error")
    monkeypatch.setattr(account, "models", unavailable)
    page = open_settings(client, pair(sec, client))
    assert "โหลดรายการโมเดลไม่สำเร็จ" in page.text
    assert "generated provider error" not in page.text
    assert account.status()["model"] == "vision-test"
    assert '<select' not in page.text


def test_dynamic_account_and_model_content_is_escaped(setup, monkeypatch):
    sec, account, client = setup
    connect(account)
    record = account.store.load()
    record["email"] = '<script>alert("account")</script>'
    account.store.save(record)
    async def models():
        return [{"slug": '\"><script>alert(1)</script>', "display_name": '<img src=x onerror=alert(1)>'}]
    monkeypatch.setattr(account, "models", models)
    page = open_settings(client, pair(sec, client))
    assert '<script>' not in page.text
    assert '<img' not in page.text
    assert '&lt;script&gt;' in page.text
    assert 'default-src \'none\'' in page.headers["content-security-policy"]


def test_cli_generates_only_short_lived_pair_code(setup, monkeypatch, capsys):
    sec, _, _ = setup
    monkeypatch.setattr(local_security, "security", sec)
    local_security.main(["pair"])
    output = capsys.readouterr().out
    code = re.search(r"[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}", output)[0]
    assert "Settings management" in output
    assert not sec.initialized()
    assert code not in (sec.store.directory / "extension-pairing.json").read_text()
    assert sec.redeem_credentials(code, allow_settings=True)["settings_token"]


def test_management_credential_can_revoke_its_pairing_without_reader_credential(setup):
    sec, _, client = setup
    credentials = pair(sec, client)
    result = client.post("/api/v1/pair/revoke", headers=headers(credentials))
    assert result.status_code == 200
    assert not sec.current_generation()
    assert not sec.verify_capability("Bearer " + credentials["token"])


def test_settings_session_expiry_requires_reopening_from_extension(setup):
    sec, _, client = setup
    credentials = pair(sec, client)
    page = open_settings(client, credentials)
    sid = client.cookies.get("manga_session")
    oauth_routes._sessions[sid]["expires"] = time.monotonic() - 1
    assert client.post("/auth/start", data={"csrf": csrf(page)}, follow_redirects=False).status_code == 403
    assert "ยังไม่ได้อนุญาตการตั้งค่า" in client.get("/settings").text
    assert "เชื่อมต่อ ChatGPT" in open_settings(client, credentials).text
