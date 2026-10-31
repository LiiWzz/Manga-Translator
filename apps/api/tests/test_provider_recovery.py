"""Default-provider and recovery behavior through real API/provider seams."""
import asyncio
import io
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main, reader_vision
from app.local_security import require_extension
from app.provider_errors import AuthError
from app.siwc import ChatGPTAuth, PERMISSION
from app.siwc_store import CredentialStore


@pytest.fixture
def client():
    main.app.dependency_overrides[require_extension] = lambda: None
    try:
        yield TestClient(main.app, base_url="http://127.0.0.1:8000")
    finally:
        main.app.dependency_overrides.pop(require_extension, None)


def image():
    out = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(out, "PNG")
    return {"file": ("generated.png", out.getvalue(), "image/png")}


@pytest.mark.parametrize("provider", [None, "mock"])
def test_default_and_mock_reader_never_call_openai(client, monkeypatch, provider):
    if provider is None:
        monkeypatch.delenv("TRANSLATOR_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("TRANSLATOR_PROVIDER", provider)
    async def forbidden(*args, **kwargs):
        pytest.fail("Mock mode must never call OAuth inference")
    monkeypatch.setattr(reader_vision.auth, "infer", forbidden)
    assert client.get("/health").json()["provider"] == "mock"
    result = client.post("/api/v1/reader/translate", files=image())
    assert result.status_code == 200
    assert result.json()["model"] == "mock-demo"
    assert "[DEMO]" in result.json()["regions"][0]["translated_text"]
    assert asyncio.run(main.translate_texts(["Hello"])) == ["[TH DEMO] Hello"]


def test_provider_change_invalidates_reader_cache(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "chatgpt_oauth")
    oauth = reader_vision.cache_profile()
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    assert reader_vision.cache_profile() != oauth


def provider_auth(tmp_path, response):
    def transport(request):
        return response(request)
    auth = ChatGPTAuth(CredentialStore(tmp_path), httpx.MockTransport(transport))
    auth.store.save({"access_token": "generated-access", "refresh_token": "generated-refresh",
                     "expires_at": time.time() + 3600, "scopes": [PERMISSION], "selected_model": "generated-model"})
    return auth


@pytest.mark.parametrize("status,code,category,stop", [
    (429, "subscription_sharing_usage_limit_exceeded", "usage_limit", True),
    (400, "subscription_sharing_unsupported_capability", "unsupported_capability", True),
    (403, "subscription_sharing_user_not_eligible", "permission_required", True),
    (503, "subscription_sharing_usage_unavailable", "provider_unavailable", False),
    (400, "unrecognized-error", "invalid_response", False),
])
def test_inference_preserves_safe_error_categories(tmp_path, status, code, category, stop):
    auth = provider_auth(tmp_path, lambda request: httpx.Response(status, headers={"x-request-id": "req_generated"},
        json={"error": {"code": code, "message": "PRIVATE generated provider text", "param": "input"}}))
    original = auth.store.load()
    with pytest.raises(AuthError) as captured:
        asyncio.run(auth.infer("generated input"))
    error = captured.value
    assert error.code == category
    assert error.stop_queue is stop
    assert error.upstream_status == status
    assert error.request_id == "req_generated"
    assert "PRIVATE" not in str(error.public())
    assert auth.store.load() == original


def test_stream_failure_preserves_usage_limit_code(tmp_path):
    auth = provider_auth(tmp_path, lambda request: httpx.Response(200,
        content='data: {"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded","message":"PRIVATE"}}}\n\n'))
    with pytest.raises(AuthError) as captured:
        asyncio.run(auth.infer("generated input"))
    assert captured.value.code == "usage_limit"
    assert "PRIVATE" not in str(captured.value)


def test_reader_returns_safe_error_and_bound_model(client, monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "chatgpt_oauth")
    store = CredentialStore(tmp_path)
    store.save({"selected_model": "generated-model-a"})
    monkeypatch.setattr(reader_vision.auth, "store", store)
    async def success(*args):
        return []
    monkeypatch.setattr(reader_vision, "translate_image", success)
    result = client.post("/api/v1/reader/translate", files=image())
    assert result.status_code == 200
    assert result.json()["model"] == "generated-model-a"
    async def limit(*args):
        raise AuthError(code="usage_limit", status=429)
    monkeypatch.setattr(reader_vision, "translate_image", limit)
    failed = client.post("/api/v1/reader/translate", files=image())
    assert failed.status_code == 429
    assert failed.json()["detail"]["stop_queue"]
    assert failed.json()["detail"]["code"] == "usage_limit"


def test_response_cannot_be_relabeled_after_account_generation_changes(client, monkeypatch):
    async def change(*args):
        reader_vision.auth.generation += 1
        return []
    monkeypatch.setattr(reader_vision, "translate_image", change)
    generation = reader_vision.auth.generation
    try:
        result = client.post("/api/v1/reader/translate", files=image())
        assert result.status_code == 409
        assert "model" not in result.json()
    finally:
        reader_vision.auth.generation = generation
