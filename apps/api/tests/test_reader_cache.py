"""Cache identities expose no account details and fence settings changes."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import reader_vision
from app.local_security import require_extension, require_extension_identity
from app.main import app
from app.siwc_store import CredentialStore


@pytest.fixture
def profile_store(monkeypatch, tmp_path):
    store = CredentialStore(tmp_path)
    store.save({"selected_model": "vision-test", "subject": "test-account", "issuer": "test-issuer",
                "access_token": "test-only-access", "refresh_token": "test-only-refresh", "email": "test@example.invalid"})
    monkeypatch.setattr(reader_vision.auth, "store", store)
    return store


@pytest.fixture
def client(profile_store):
    app.dependency_overrides[require_extension] = lambda: None
    app.dependency_overrides[require_extension_identity] = lambda: None
    try:
        yield TestClient(app, base_url="http://127.0.0.1:8000")
    finally:
        app.dependency_overrides.pop(require_extension, None)
        app.dependency_overrides.pop(require_extension_identity, None)


def image():
    stream = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(stream, "PNG")
    return {"file": ("generated.png", stream.getvalue(), "image/png")}


def test_profile_is_authenticated_and_checks_origin():
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    assert c.get("/api/v1/reader/profile").status_code == 401
    assert c.get("/api/v1/reader/profile", headers={"origin": "https://attacker.invalid"}).status_code == 403


def test_profile_contains_only_an_opaque_fingerprint(client):
    response = client.get("/api/v1/reader/profile")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"fingerprint"}
    assert len(response.json()["fingerprint"]) == 64
    assert all(value not in response.text for value in ("test-only", "test-account", "test-issuer", "test@example", "vision-test"))


@pytest.mark.parametrize("field", ["selected_model", "subject", "issuer"])
def test_model_and_account_changes_invalidate_profile(profile_store, field):
    original = reader_vision.cache_profile()
    saved = profile_store.load()
    saved[field] += "-changed"
    profile_store.save(saved)
    assert reader_vision.cache_profile() != original


def test_token_rotation_does_not_invalidate_dialogue(profile_store):
    original = reader_vision.cache_profile()
    saved = profile_store.load()
    saved["access_token"] = "rotated-test-token"
    profile_store.save(saved)
    assert reader_vision.cache_profile() == original


@pytest.mark.parametrize("name,value", [("VISION_INSTRUCTIONS", "changed prompt"),
                                       ("READER_PIPELINE_VERSION", "next"),
                                       ("GLOSSARY_REVISION", "next"), ("MAX_IMAGE_SIDE", 2000)])
def test_pipeline_prompt_glossary_and_image_policy_invalidate_profile(profile_store, monkeypatch, name, value):
    original = reader_vision.cache_profile()
    monkeypatch.setattr(reader_vision, name, value)
    assert reader_vision.cache_profile() != original


def test_stale_profile_is_rejected_before_inference(client, monkeypatch):
    async def fail(*args, **kwargs):
        pytest.fail("Stale settings must not spend model quota")
    monkeypatch.setattr(reader_vision, "translate_image", fail)
    response = client.post("/api/v1/reader/translate", files=image(), data={"profile": "0" * 64})
    assert response.status_code == 409


def test_settings_change_during_inference_cannot_be_cached(client, profile_store, monkeypatch):
    original = reader_vision.cache_profile()
    async def fake(*args, **kwargs):
        saved = profile_store.load()
        saved["selected_model"] = "changed-during-inference"
        profile_store.save(saved)
        return []
    monkeypatch.setattr(reader_vision, "translate_image", fake)
    response = client.post("/api/v1/reader/translate", files=image(), data={"profile": original})
    assert response.status_code == 409
    assert "regions" not in response.json()


def test_matching_profile_is_returned_with_translations(client, monkeypatch):
    async def fake(*args, **kwargs):
        return []
    monkeypatch.setattr(reader_vision, "translate_image", fake)
    original = reader_vision.cache_profile()
    response = client.post("/api/v1/reader/translate", files=image(), data={"profile": original})
    assert response.status_code == 200
    assert response.json()["profile"] == original


def test_profile_checks_do_not_spend_translation_admission_budget(profile_store, monkeypatch):
    from app import local_security
    security = local_security.LocalSecurity(profile_store)
    monkeypatch.setattr(security, "verify_capability", lambda header: header == "Bearer test-only-capability")
    monkeypatch.setattr(local_security, "security", security)
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    for _ in range(15):
        assert c.get("/api/v1/reader/profile", headers={"authorization": "Bearer test-only-capability"}).status_code == 200
    assert security.requests == []
    assert security.inflight == 0
