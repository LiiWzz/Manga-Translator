import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.bubble_renderer import TextRegion, _thai_clusters, overlay_data_url, render_translations


def flat_bubble():
    im = Image.new("RGB", (480, 250), (192, 68, 46))
    d = ImageDraw.Draw(im)
    d.ellipse((40,18,430,235),fill=(0,0,0),outline=(255,255,255),width=3)
    d.text((140,110),"ARE YOU READY?",fill="white")
    return im


def test_dark_balloon_replacement_preserves_source():
    im = flat_bubble()
    before = im.tobytes()
    overlay,n,skipped = render_translations(im,[TextRegion((135,105,150,22),"ARE YOU READY?")],["พร้อมหรือยัง?"])
    assert n==1,skipped
    assert im.tobytes()==before
    assert overlay.getpixel((140,110))[:3]==(0,0,0)
    assert overlay.getpixel((45,28))[3]==0
    assert overlay_data_url(overlay).startswith("data:image/png;base64,")


def test_mock_never_covers_art():
    overlay,n,skipped = render_translations(flat_bubble(),[TextRegion((135,105,150,22),"TEST")],["[TH DEMO] TEST"])
    assert n==0
    assert skipped[0]["reason"]=="not_thai"
    assert overlay.getbbox() is None


def test_artwork_is_not_blanked():
    array = np.indices((200,400)).sum(axis=0)%2*255
    textured = Image.fromarray(np.stack([array]*3,axis=2).astype(np.uint8),"RGB")
    _,n,skipped = render_translations(textured,[TextRegion((100,70,160,25),"HI")],["สวัสดี"])
    assert n==0
    assert skipped[0]["reason"]=="textured_or_unknown_background"


def test_combining_marks_remain_attached():
    assert "ก้" in _thai_clusters("ก้ไก่")
    assert "้" not in _thai_clusters("ก้ไก่")


def test_mismatched_translation_count_is_rejected():
    with pytest.raises(ValueError):
        render_translations(flat_bubble(),[TextRegion((1,1,50,50),"HI")],[])
