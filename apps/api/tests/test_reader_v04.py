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
    from app import main
    monkeypatch.setattr(main,"extract_regions",lambda _: [([35,35,90,25],"HELLO",.93)])
    captured=[]
    async def fake(texts,context=""):
        captured.append((texts,context))
        return ["สวัสดี"]
    monkeypatch.setattr(main,"translate_texts",fake)
    app.dependency_overrides[require_extension]=lambda:None
    try:
        c=TestClient(app,base_url="http://127.0.0.1:8000")
        r=c.post("/api/v1/reader/translate",
                 data={"context":"previous dialogue"},
                 files={"file":("page.png",picture(),"image/png")})
        assert r.status_code==200,r.text
        data=r.json()
        assert data["regions"][0]["translated_text"]=="สวัสดี"
        assert "overlay_data_url" not in data
        assert captured==[(["HELLO"],"previous dialogue")]
        assert c.post("/api/v1/reader/translate",data={"context":"a"*1501},
                      files={"file":("page.png",picture(),"image/png")}).status_code==422
    finally:
        app.dependency_overrides.pop(require_extension,None)

def test_reader_requires_pairing():
    c=TestClient(app,base_url="http://127.0.0.1:8000")
    r=c.post("/api/v1/reader/translate",files={"file":("page.png",picture(),"image/png")})
    assert r.status_code==401

def test_reader_rejects_invalid_origin():
    c=TestClient(app,base_url="http://127.0.0.1:8000")
    assert c.post("/api/v1/reader/translate",headers={"origin":"https://evil.example"},
                  files={"file":("page.png",picture(),"image/png")}).status_code==403
