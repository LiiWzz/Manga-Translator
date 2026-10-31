"""Pair-once ownership, browser session handoff and Settings UX regressions."""
import hashlib
import asyncio
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
    response = client.post("/auth/model", data={"csrf": csrf(page), "slug": "vision-test", "version": account.model_selection_version()}, follow_redirects=False)
    assert response.status_code == 303
    assert account.status()["model"] == "vision-test"
    assert 'value="vision-test" selected' in client.get("/settings").text
    denied = client.post("/auth/model", data={"csrf": csrf(page), "slug": "not-in-catalog", "version": account.model_selection_version()})
    assert denied.status_code == 400
    assert "บันทึกโมเดลไม่สำเร็จ" in denied.text
    assert account.status()["model"] == "vision-test"


def test_browser_model_form_cannot_overwrite_a_newer_reader_choice(setup):
    sec, account, client = setup
    connect(account)
    page = open_settings(client, pair(sec, client))
    version = account.model_selection_version()
    record = account.store.load()
    record["selected_model"] = "newer-reader-choice"
    account.store.save(record)
    result = client.post("/auth/model", data={"csrf": csrf(page), "slug": "vision-test", "version": version})
    assert result.status_code == 409
    assert account.status()["model"] == "newer-reader-choice"


@pytest.mark.parametrize("change", ["revoke", "re-pair", "expire"])
def test_browser_model_save_rechecks_authority_after_provider_io(setup, monkeypatch, change):
    sec, account, client = setup
    connect(account)
    page = open_settings(client, pair(sec, client))
    version = account.model_selection_version()
    async def models():
        if change == "expire":
            oauth_routes._sessions[client.cookies.get("manga_session")]["expires"] = 0
        elif change == "re-pair":
            sec.redeem_credentials(sec.issue_pairing(manage_settings=True), allow_settings=True)
        else:
            sec.revoke()
        return [{"slug": "vision-test", "display_name": "Generated model"}]
    monkeypatch.setattr(account, "models", models)
    result = client.post("/auth/model", data={"csrf": csrf(page), "slug": "vision-test", "version": version}, follow_redirects=False)
    assert result.status_code == 403
    assert account.status()["model"] is None


def test_settings_terminal_expiry_promotes_reconnect_with_saved_client_id(setup):
    from urllib.parse import parse_qs, urlparse
    sec, account, client = setup
    connect(account)
    record = account.store.load()
    record.update(client_id="oaiapp_generated", subject="generated-account", expires_at=0)
    account.store.save(record)
    account.transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(siwc.AuthError):
        asyncio.run(account.access_token())
    page = open_settings(client, pair(sec, client))
    assert "ต้องเชื่อมต่อใหม่" in page.text
    assert '<form method="post" action="/auth/reconnect">' in page.text
    result = client.post("/auth/reconnect", data={"csrf": csrf(page)}, follow_redirects=False)
    query = parse_qs(urlparse(result.headers["location"]).query)
    assert query["client_id"] == ["oaiapp_generated"]
    assert "prompt" not in query


def test_explicit_plan_permission_recovery_reuses_registration_and_requests_consent(setup):
    from urllib.parse import parse_qs, urlparse
    sec, account, client = setup
    connect(account)
    record = account.store.load()
    record.update(client_id="oaiapp_generated", subject="generated-account", scopes=["openid"])
    account.store.save(record)
    page = open_settings(client, pair(sec, client))
    assert "อนุญาตใช้แผน ChatGPT" in page.text
    result = client.post("/auth/reconnect", data={"csrf": csrf(page)}, follow_redirects=False)
    query = parse_qs(urlparse(result.headers["location"]).query)
    assert query["client_id"] == ["oaiapp_generated"]
    assert query["prompt"] == ["consent"]
    assert siwc.PERMISSION in query["scope"][0].split()


def test_callback_rechecks_pairing_after_code_exchange(setup, monkeypatch):
    sec, account, client = setup
    connect(account)
    page = open_settings(client, pair(sec, client))
    started = client.post("/auth/start", data={"csrf": csrf(page)}, follow_redirects=False)
    assert started.status_code == 303
    attempt = account.pending
    original = account.store.load()
    async def validate(*args):
        sec.revoke()
        return {"sub": "new-generated-account"}
    monkeypatch.setattr(account, "_validate_id_token", validate)
    account.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "access_token": "generated-new", "refresh_token": "generated-new-refresh",
        "id_token": "generated-id", "scope": siwc.PERMISSION, "expires_in": 3600}))
    result = client.get("/auth/callback", params={"code": "generated-code", "state": attempt.state,
                        "client_id": "oaiapp_generated"}, follow_redirects=False)
    assert result.status_code == 403
    assert account.store.load() == original


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


def test_extension_catalog_and_model_change_require_management_authority(setup, monkeypatch):
    sec, account, client = setup
    connect(account, "previous-test")
    legacy = pair(sec, client, management=False)
    reader_headers = {"origin": ORIGIN, "authorization": "Bearer " + legacy["token"]}
    assert client.get("/api/v1/settings/models", headers=reader_headers).status_code == 401
    assert client.post("/api/v1/settings/model", headers=reader_headers, json={"slug": "vision-test", "version": "a" * 64}).status_code == 401
    credentials = pair(sec, client)
    response = client.get("/api/v1/settings/models", headers=headers(credentials))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["models"] == [{"slug": "vision-test", "display_name": "Test model"}]
    assert set(response.json()) == {"models", "model", "version"}
    assert all(value not in response.text for value in ["generated-test-access", "generated-test-refresh", "reader@example.invalid", *credentials.values()])
    from app import reader_vision
    monkeypatch.setattr(reader_vision, "auth", account)
    previous = reader_vision.cache_profile()
    selected = client.post("/api/v1/settings/model", headers=headers(credentials),
                           json={"slug": "vision-test", "version": response.json()["version"]})
    assert selected.status_code == 200
    assert selected.headers["cache-control"] == "no-store"
    assert selected.json()["model"] == "vision-test"
    assert selected.json()["version"] != response.json()["version"]
    assert reader_vision.cache_profile() != previous
    assert sec.requests == [] and sec.inflight == 0


@pytest.mark.parametrize("origin", [None, "null", HOST, "https://evil.invalid", "http://127.0.0.1:9000"])
def test_extension_model_routes_deny_foreign_origins(setup, origin):
    sec, account, client = setup
    connect(account)
    credentials = pair(sec, client)
    request_headers = {"authorization": "Bearer " + credentials["settings_token"]}
    if origin is not None:
        request_headers["origin"] = origin
    assert client.get("/api/v1/settings/models", headers=request_headers).status_code == 403
    assert client.post("/api/v1/settings/model", headers=request_headers,
                       json={"slug": "vision-test", "version": "a" * 64}).status_code == 403


def test_invalid_model_does_not_change_saved_selection(setup):
    sec, account, client = setup
    connect(account, "previous-test")
    credentials = pair(sec, client)
    result = client.post("/api/v1/settings/model", headers=headers(credentials),
                         json={"slug": "not-in-catalog", "version": account.model_selection_version()})
    assert result.status_code == 502
    assert account.status()["model"] == "previous-test"


def test_stale_model_selection_cannot_overwrite_another_settings_page(setup):
    sec, account, client = setup
    connect(account, "previous-test")
    credentials = pair(sec, client)
    version = account.model_selection_version()
    record = account.store.load()
    record["selected_model"] = "chosen-elsewhere"
    account.store.save(record)
    result = client.post("/api/v1/settings/model", headers=headers(credentials),
                         json={"slug": "vision-test", "version": version})
    assert result.status_code == 409
    assert account.status()["model"] == "chosen-elsewhere"


@pytest.mark.parametrize("operation", ["catalog", "save"])
def test_account_change_during_model_fetch_rejects_stale_operation(setup, monkeypatch, operation):
    sec, account, client = setup
    connect(account, "previous-test")
    credentials = pair(sec, client)
    version = account.model_selection_version()
    async def models():
        record = account.store.load()
        record["subject"] = "changed-generated-account"
        account.store.save(record)
        return [{"slug": "vision-test", "display_name": "Test model"}]
    monkeypatch.setattr(account, "models", models)
    result = (client.get("/api/v1/settings/models", headers=headers(credentials)) if operation == "catalog" else
              client.post("/api/v1/settings/model", headers=headers(credentials), json={"slug": "vision-test", "version": version}))
    assert result.status_code == 409
    assert account.status()["model"] == "previous-test"


@pytest.mark.parametrize("operation", ["catalog", "save"])
def test_revocation_during_model_fetch_rechecks_authority_before_return_or_write(setup, monkeypatch, operation):
    sec, account, client = setup
    connect(account, "previous-test")
    credentials = pair(sec, client)
    version = account.model_selection_version()
    async def models():
        sec.revoke()
        return [{"slug": "vision-test", "display_name": "Test model"}]
    monkeypatch.setattr(account, "models", models)
    result = (client.get("/api/v1/settings/models", headers=headers(credentials)) if operation == "catalog" else
              client.post("/api/v1/settings/model", headers=headers(credentials), json={"slug": "vision-test", "version": version}))
    assert result.status_code == 401
    assert account.status()["model"] == "previous-test"


def test_refreshing_tokens_does_not_invalidate_model_selection_version(setup):
    _, account, _ = setup
    connect(account, "vision-test")
    version = account.model_selection_version()
    record = account.store.load()
    record.update(access_token="generated-rotated-access", refresh_token="generated-rotated-refresh", expires_at=time.time() + 5000)
    account.store.save(record)
    assert account.model_selection_version() == version
