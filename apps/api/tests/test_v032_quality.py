"""v0.3.2 adversarial tests for OCR grouping, sanitization, debug API."""
import base64
import io
import pytest
from PIL import Image
from app.bubble_renderer import TextRegion, render_translations
from app.ocr_grouping import group_lines, OCRAnalysis, diagnostic_packet
from app.text_quality import clean_translation


def test_ocr_groups_vertically_stacked_dialogue():
    lines = [TextRegion((100, 100, 150, 24), "DON'T YOU"),
             TextRegion((103, 131, 146, 22), "WANT TO MEET"),
             TextRegion((110, 160, 133, 22), "DAM SAYOUNG?")]
    grouped = group_lines(lines)
    assert len(grouped) == 1
    assert grouped[0].source_text == "DON'T YOU WANT TO MEET DAM SAYOUNG?"


def test_ocr_preserves_side_by_side_bubbles():
    lines = [TextRegion((20, 70, 60, 19), "HELLO"),
             TextRegion((260, 72, 80, 19), "WORLD")]
    assert len(group_lines(lines)) == 2


def test_malformed_and_tofu_characters_never_drawn():
    assert clean_translation("สวัสดี\u0000ครับ")[0] == "สวัสดีครับ"
    assert clean_translation("ปีศาจ □")[1] == "replacement_character_or_tofu"
    assert clean_translation("แปลไม่ได้ \ufffd")[1] == "replacement_character_or_tofu"


def test_debug_packet_coordinates_and_rejected_reason():
    a = OCRAnalysis([TextRegion((10, 20, 30, 40), "HELLO", .9)],
                    [TextRegion((10, 20, 30, 40), "HELLO", .9)],
                    [{"reason": "low_confidence", "index": 1}])
    packet = diagnostic_packet(a)
    assert packet["ocr_lines"][0]["bbox"] == [10, 20, 30, 40]
    assert packet["ocr_rejected"][0]["reason"] == "low_confidence"


def test_stylized_irregular_artwork_is_not_painted():
    import numpy as np
    arr = (np.indices((180, 300)).sum(axis=0) % 2 * 255).astype("uint8")
    image = Image.fromarray(np.stack((arr, arr, arr), axis=2))
    overlay, applied, skipped = render_translations(
        image, [TextRegion((40, 40, 120, 40), "HELLO", 0.9)], ["สวัสดี"])
    assert applied == 0
    assert overlay.getbbox() is None
    assert skipped[0]["reason"] == "textured_or_unknown_background"


def test_tofu_translation_is_skipped_without_overlay():
    image = Image.new("RGB", (300, 180), "white")
    overlay, applied, skipped = render_translations(
        image, [TextRegion((50, 50, 150, 30), "DEMON", 0.9)], ["ปีศาจ □"])
    assert applied == 0
    assert skipped[0]["reason"] == "replacement_character_or_tofu"
    assert overlay.getbbox() is None
