"""Overlapping OAuth operations use generated credentials and isolated stores."""
import asyncio
import time

import httpx
import pytest

from app.siwc import AuthError, ChatGPTAuth, ISSUER, PERMISSION
from app.siwc_store import CredentialStore


def account(auth, *, expired=False, subject="generated-account", model="model-a"):
    record = {"client_id": "oaiapp_generated", "subject": subject, "issuer": ISSUER,
              "email": "reader@example.invalid", "access_token": "generated-access",
              "refresh_token": "generated-refresh", "scopes": [PERMISSION],
              "expires_at": time.time() + (-1 if expired else 3600), "selected_model": model}
    auth.store.save(record)
    return record


def rotated():
    return {"access_token": "generated-rotated-access", "refresh_token": "generated-rotated-refresh",
            "expires_in": 3600, "scope": PERMISSION}


def test_refresh_keeps_a_model_saved_while_its_request_was_pending(tmp_path):
    async def scenario():
        catalog_entered, release_catalog = asyncio.Event(), asyncio.Event()
        refresh_entered, release_refresh = asyncio.Event(), asyncio.Event()

        async def transport(request):
            if request.url.path.endswith("/models"):
                catalog_entered.set()
                await release_catalog.wait()
                return httpx.Response(200, json={"models": [{"slug": "model-b", "visibility": "list"}]})
            refresh_entered.set()
            await release_refresh.wait()
            return httpx.Response(200, json=rotated())

        auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(transport))
        account(auth)
        saving = asyncio.create_task(auth.select_model("model-b", expected_version=auth.model_selection_version()))
        await catalog_entered.wait()
        record = auth.store.load()
        record["expires_at"] = 0
        auth.store.save(record)
        refreshing = asyncio.create_task(auth.access_token())
        await refresh_entered.wait()
        release_catalog.set()
        await saving
        assert auth.status()["model"] == "model-b"
        release_refresh.set()
        await refreshing
        assert auth.status()["model"] == "model-b"
        assert auth.store.load()["refresh_token"] == rotated()["refresh_token"]

    asyncio.run(scenario())


def test_refresh_cannot_restore_an_account_replaced_by_sign_in(tmp_path, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def transport(request):
            if "grant_type=refresh_token" in request.content.decode():
                entered.set()
                await release.wait()
                return httpx.Response(200, json=rotated())
            return httpx.Response(200, json={**rotated(), "id_token": "generated-id"})

        auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(transport))
        account(auth, expired=True)
        auth.start()
        pending = auth.pending
        async def validate(*args):
            return {"sub": "new-account", "email": "new@example.invalid"}
        monkeypatch.setattr(auth, "_validate_id_token", validate)
        refreshing = asyncio.create_task(auth.access_token())
        await entered.wait()
        await auth.callback("generated-code", pending.state, "oaiapp_new", None)
        release.set()
        await asyncio.gather(refreshing, return_exceptions=True)
        assert auth.store.load()["subject"] == "new-account"

    asyncio.run(scenario())


def test_logout_fences_a_callback_already_exchanging_its_code(tmp_path, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def transport(request):
            if request.url.path.endswith("/token"):
                entered.set()
                await release.wait()
                return httpx.Response(200, json={**rotated(), "id_token": "generated-id"})
            return httpx.Response(200, json={"revocation_endpoint": "https://auth.openai.com/revoke"})
        auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(transport))
        account(auth)
        auth.start(reconnect=True)
        pending = auth.pending
        async def validate(*args):
            return {"sub": "generated-account"}
        monkeypatch.setattr(auth, "_validate_id_token", validate)
        signing_in = asyncio.create_task(auth.callback("generated-code", pending.state, None, None))
        await entered.wait()
        await auth.logout()
        release.set()
        await asyncio.gather(signing_in, return_exceptions=True)
        assert not auth.status()["connected"]

    asyncio.run(scenario())


def test_terminal_refresh_failure_requires_reconnect_and_retains_registration(tmp_path):
    auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": "invalid_grant"})))
    account(auth, expired=True)
    with pytest.raises(AuthError):
        asyncio.run(auth.access_token())
    assert not auth.status()["connected"]
    assert auth.status()["reconnect_required"]
    assert auth.store.load()["client_id"] == "oaiapp_generated"
    assert not auth.store.load().get("refresh_token")


def test_temporary_refresh_failure_preserves_credentials(tmp_path):
    auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(
        lambda request: httpx.Response(503, json={"detail": "generated outage"})))
    original = account(auth, expired=True)
    with pytest.raises(AuthError):
        asyncio.run(auth.access_token())
    assert auth.store.load() == original


@pytest.mark.parametrize("terminal", [False, True])
def test_old_refresh_result_cannot_disconnect_or_restore_same_account_reconnection(tmp_path, monkeypatch, terminal):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def transport(request):
            if "grant_type=refresh_token" in request.content.decode():
                entered.set()
                await release.wait()
                return httpx.Response(400, json={"error": "invalid_grant"}) if terminal else httpx.Response(200, json=rotated())
            return httpx.Response(200, json={**rotated(), "access_token": "new-sign-in-access", "id_token": "generated-id"})
        auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(transport))
        account(auth, expired=True)
        auth.start(reconnect=True)
        pending = auth.pending
        async def validate(*args):
            return {"sub": "generated-account"}
        monkeypatch.setattr(auth, "_validate_id_token", validate)
        refreshing = asyncio.create_task(auth.access_token())
        await entered.wait()
        await auth.callback("generated-code", pending.state, None, None)
        release.set()
        await asyncio.gather(refreshing, return_exceptions=True)
        assert auth.store.load()["access_token"] == "new-sign-in-access"
        assert auth.status()["connected"]
    asyncio.run(scenario())


def test_refresh_rotates_credentials_even_when_plan_permission_is_removed(tmp_path):
    auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(
        lambda request: httpx.Response(200, json={**rotated(), "scope": "openid"})))
    account(auth, expired=True)
    with pytest.raises(AuthError):
        asyncio.run(auth.access_token())
    assert auth.store.load()["refresh_token"] == rotated()["refresh_token"]
    assert not auth.status()["plan_usage_enabled"]
