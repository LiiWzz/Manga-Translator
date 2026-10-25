"""Thai layout regression: no broken Thai words and no glyph overflow."""
from PIL import ImageFont
from app.bubble_renderer import _wrap, _fit, FONT_CANDIDATES
from pathlib import Path
import pytest


def _font():
    path = next((p for p in FONT_CANDIDATES if p and Path(p).is_file()), None)
    if path is None:
        pytest.skip("Noto Thai not installed")
    return path


def test_thai_wrap_respects_words():
    path = _font()
    font = ImageFont.truetype(path, 20)
    sentence = "สวัสดีครับ วันนี้อากาศดีมาก"
    lines = _wrap(sentence, font, 110)
    assert len(lines) >= 2
    assert "".join(lines).replace(" ", "") == sentence.replace(" ", "")
    assert all(font.getlength(line) <= 110 for line in lines)


def test_layout_never_overflows_or_truncates():
    path = _font()
    text = "สวัสดีครับ ยินดีต้อนรับสู่การผจญภัยครั้งใหม่"
    layout = _fit(text, 180, 150, path)
    assert layout is not None
    font, lines, spacing, line_height = layout
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
    assert len(lines) * line_height + (len(lines)-1)*spacing <= 138
    assert all(font.getbbox(line, anchor="lt")[2] -
               font.getbbox(line, anchor="lt")[0] <= 168 for line in lines)


def test_overlong_token_is_not_broken_through_thai_marks():
    path = _font()
    font = ImageFont.truetype(path, 20)
    assert _wrap("การทดสอบ", font, 1) == []
