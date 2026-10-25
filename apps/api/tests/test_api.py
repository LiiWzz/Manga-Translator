import io
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (120, 100), "white").save(buffer, format="PNG")
    return buffer.getvalue()

def test_health(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    assert client.get("/health").json()["status"] == "ok"

def test_reject_mime():
    r = client.post("/api/v1/translate", files={"file": ("x.txt", b"x", "text/plain")})
    assert r.status_code == 415

def test_reject_corrupt_image():
    r = client.post("/api/v1/translate", files={"file": ("x.png", b"bad", "image/png")})
    assert r.status_code == 400

def test_mock_translation(monkeypatch):
    from app import main
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    monkeypatch.setattr(main, "extract_regions", lambda img: [([10, 20, 70, 25], "Hello there", .97)])
    r = client.post("/api/v1/translate", files={"file": ("x.png", image_bytes(), "image/png")})
    assert r.status_code == 200
    assert r.json()["regions"][0]["translated_text"] == "[TH DEMO] Hello there"

def test_empty_regions(monkeypatch):
    from app import main
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    monkeypatch.setattr(main, "extract_regions", lambda img: [])
    r = client.post("/api/v1/translate", files={"file": ("x.png", image_bytes(), "image/png")})
    assert r.status_code == 200
    assert r.json()["regions"] == []
