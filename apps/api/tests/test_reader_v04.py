"""v0.4 non-destructive reader endpoint and context regression tests."""
from fastapi.testclient import TestClient
from PIL import Image
import io
import pytest
from app.main import app
from app.local_security import require_extension

def picture():
    im=Image.new("RGB",(400,260),"white")
    out=io.BytesIO()
    im.save(out,"PNG")
    return out.getvalue()

def test_reader_translation_is_non_destructive(monkeypatch):
    from app import reader_vision
    captured = []
    async def fake(image, context=""):
        captured.append(context)
        return [{"source_text": "ELDER, DOESN'T THE YOUNG LEADER SEEM EVEN MORE IMPRESSIVE NOW?",
                 "translated_text": "ท่านผู้อาวุโส ท่านผู้นำหนุ่มดูน่าประทับใจยิ่งกว่าเดิมไหม?",
                 "bbox": None, "confidence": None}]
    monkeypatch.setattr(reader_vision, "translate_image", fake)
    app.dependency_overrides[require_extension] = lambda: None
    try:
        c = TestClient(app, base_url="http://127.0.0.1:8000")
        r = c.post("/api/v1/reader/translate",
                   data={"context": "previous dialogue"},
                   files={"file": ("page.png", picture(), "image/png")})
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["regions"]) == 1
        assert data["reader_mode"] == "vision-first"
        assert "overlay_data_url" not in data
        assert captured == ["previous dialogue"]
        assert c.post("/api/v1/reader/translate", data={"context": "a" * 1501},
                      files={"file": ("page.png", picture(), "image/png")}).status_code == 422
    finally:
        app.dependency_overrides.pop(require_extension, None)


def test_reader_requires_pairing():
    c=TestClient(app,base_url="http://127.0.0.1:8000")
    r=c.post("/api/v1/reader/translate",files={"file":("page.png",picture(),"image/png")})
    assert r.status_code==401

def test_reader_rejects_invalid_origin():
    c=TestClient(app,base_url="http://127.0.0.1:8000")
    assert c.post("/api/v1/reader/translate",headers={"origin":"https://evil.example"},
                  files={"file":("page.png",picture(),"image/png")}).status_code==403


def test_reader_keeps_translations_when_another_balloon_is_ellipsis(monkeypatch):
    from app import reader_vision
    async def infer(*args, **kwargs):
        return ('{"dialogues":[{"source_text":"HELLO THERE","translated_text":"สวัสดี"},'
                '{"source_text":"......","translated_text":"......"}]}')
    monkeypatch.setattr(reader_vision.auth, "infer", infer)
    app.dependency_overrides[require_extension] = lambda: None
    try:
        response = TestClient(app, base_url="http://127.0.0.1:8000").post(
            "/api/v1/reader/translate",
            files={"file": ("page.png", picture(), "image/png")})
        assert response.status_code == 200, response.text
        assert [row["translated_text"] for row in response.json()["regions"]] == ["สวัสดี", "......"]
    finally:
        app.dependency_overrides.pop(require_extension, None)


def test_reader_logs_safe_validation_reason_without_dialogue_or_image(monkeypatch, caplog):
    from app import reader_vision
    async def infer(*args, **kwargs):
        return '{"dialogues":[{"source_text":"PRIVATE COMIC TEXT","translated_text":"still English"}]}'
    monkeypatch.setattr(reader_vision.auth, "infer", infer)
    app.dependency_overrides[require_extension] = lambda: None
    try:
        response = TestClient(app, base_url="http://127.0.0.1:8000").post(
            "/api/v1/reader/translate",
            files={"file": ("private-image-name.png", picture(), "image/png")})
        assert response.status_code == 502
        assert "Reader vision rejected image (400x260)" in caplog.text
        assert "incomplete or untranslated dialogue" in caplog.text
        assert "PRIVATE COMIC TEXT" not in caplog.text
        assert "still English" not in caplog.text
        assert "private-image-name" not in caplog.text
        assert "base64" not in caplog.text
    finally:
        app.dependency_overrides.pop(require_extension, None)
