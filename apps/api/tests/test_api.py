import base64
import io
from PIL import Image,ImageDraw
from fastapi.testclient import TestClient
from app.main import app
from app.local_security import require_extension
import pytest

@pytest.fixture(autouse=True)
def legacy_api_auth_override():
    app.dependency_overrides[require_extension] = lambda: None
    yield
    app.dependency_overrides.pop(require_extension, None)

client = TestClient(app)

def sample():
    im = Image.new("RGB",(480,250),"#c94431")
    draw = ImageDraw.Draw(im)
    draw.ellipse((40,18,430,235),fill="black",outline="white",width=3)
    draw.text((140,110),"ARE YOU READY?",fill="white")
    stream=io.BytesIO()
    im.save(stream,"PNG")
    return stream.getvalue()

def send(path="/api/v1/translate-rendered"):
    return client.post(path,files={"file":("panel.png",sample(),"image/png")})

def test_health(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER","mock")
    assert client.get("/health").json()["status"]=="ok"

def test_bad_mime():
    assert client.post("/api/v1/translate-rendered",files={"file":("x.txt",b"test","text/plain")}).status_code==415

def test_mock_does_not_render(monkeypatch):
    from app import main
    monkeypatch.setenv("TRANSLATOR_PROVIDER","mock")
    monkeypatch.setattr(main,"extract_regions",lambda _: [([135,105,150,22],"ARE YOU READY?",.99)])
    response=send()
    assert response.status_code==200,response.text
    assert response.json()["applied_regions"]==0
    assert response.json()["skipped"][0]["reason"]=="not_thai"

def test_thai_render_endpoint(monkeypatch):
    from app import main
    monkeypatch.setattr(main,"extract_regions",lambda _: [([135,105,150,22],"ARE YOU READY?",.99)])
    async def thai(_): return ["พร้อมหรือยัง?"]
    monkeypatch.setattr(main,"translate_texts",thai)
    response=send()
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload["applied_regions"]==1,payload["skipped"]
    overlay=Image.open(io.BytesIO(base64.b64decode(payload["overlay_data_url"].split(",")[1])))
    assert overlay.size==(480,250)
    assert overlay.getpixel((45,28))[3]==0

def test_old_api_still_works(monkeypatch):
    from app import main
    monkeypatch.setenv("TRANSLATOR_PROVIDER","mock")
    monkeypatch.setattr(main,"extract_regions",lambda _: [([130,100,100,18],"HELLO",.9)])
    response=send("/api/v1/translate")
    assert response.status_code==200
    assert response.json()["regions"][0]["translated_text"]=="[TH DEMO] HELLO"
