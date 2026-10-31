import asyncio
import base64
import io
import json
import pytest
from PIL import Image
from app import reader_vision
from app.siwc import AuthError


def test_complete_balloon_not_fragmented():
    data = {"dialogues":[{"source_text":"ELDER, DOESN'T THE YOUNG LEADER SEEM EVEN MORE IMPRESSIVE NOW?",
                           "translated_text":"ท่านผู้อาวุโส ผู้นำหนุ่มดูน่าประทับใจยิ่งกว่าเดิมใช่ไหม?"}]}
    rows = reader_vision.validate_dialogues(json.dumps(data, ensure_ascii=False))
    assert len(rows)==1 and rows[0]["bbox"] is None


@pytest.mark.parametrize("payload", [
    '{"dialogues":[{"source_text":"my","translated_text":"my"}]}',
    '{"dialogues":[{"source_text":"HELLO","translated_text":"□"}]}',
    '{"dialogues":[{"source_text":"HELLO"}]}',
    '{"translations":["สวัสดี"]}',
    "not json",
])
def test_no_invalid_fragments_or_malformed_output(payload):
    with pytest.raises(AuthError):
        reader_vision.validate_dialogues(payload)


def test_vision_sends_image_without_guessing_coordinates(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "chatgpt_oauth")
    captured = {}
    class FakeAuth:
        async def infer(self, content, instructions=None):
            captured["content"] = content
            captured["instructions"] = instructions
            return '{"dialogues":[{"source_text":"HELLO THERE","translated_text":"สวัสดี"}]}'
    monkeypatch.setattr(reader_vision, "auth", FakeAuth())
    result=asyncio.run(reader_vision.translate_image(Image.new("RGB",(400,300),"white")))
    assert len(result)==1 and result[0]["confidence"] is None
    assert captured["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert "SAME balloon" in captured["instructions"]


@pytest.mark.parametrize("punctuation", ["......", "...", "…", "?!", "!", "?"])
def test_punctuation_only_balloon_does_not_discard_translated_dialogue(punctuation):
    entries = [
        {"source_text": "HELLO THERE", "translated_text": "สวัสดี"},
        {"source_text": punctuation, "translated_text": punctuation},
    ]
    rows = reader_vision.validate_dialogues(json.dumps({"dialogues": entries}))
    assert [row["translated_text"] for row in rows] == ["สวัสดี", punctuation]


@pytest.mark.parametrize("source,translated", [
    ("HELLO", "HELLO"), ("...", "???"), ("...", ""), ("□", "□"),
    ("", ""), ("...", "hello"), ("...", "สวัสดี"),
    ("." * 701, "." * 701),
])
def test_punctuation_exception_keeps_quality_guards(source, translated):
    with pytest.raises(AuthError):
        reader_vision.validate_dialogues(json.dumps({"dialogues": [
            {"source_text": source, "translated_text": translated}
        ]}))


def test_tall_strip_preserves_readable_width_and_overlapping_coverage(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "chatgpt_oauth")
    captured = {}
    async def infer(content, instructions=None):
        captured["content"] = content
        captured["instructions"] = instructions
        return '{"dialogues":[]}'
    monkeypatch.setattr(reader_vision.auth, "infer", infer)
    # Same dimensions as the reported image, with a synthetic vertical gradient.
    image = Image.new("RGB", (900, 16000))
    for y in range(image.height):
        image.paste((y // 64, 0, 0), (0, y, image.width, y + 1))
    assert asyncio.run(reader_vision.translate_image(image)) == []
    crops = [Image.open(io.BytesIO(base64.b64decode(block["image_url"].split(",", 1)[1])))
             for block in captured["content"] if block["type"] == "input_image"]
    assert [crop.size for crop in crops] == [(900, 3000)] * 5 + [(900, 2500)]
    assert abs(crops[0].getpixel((450, 0))[0]) <= 3
    assert abs(crops[-1].getpixel((450, 2499))[0] - 249) <= 3
    for previous, current in zip(crops, crops[1:]):
        assert abs(previous.getpixel((450, 2800))[0] - current.getpixel((450, 100))[0]) <= 3
    assert "overlap" in captured["instructions"]
    assert "once" in captured["instructions"]


def test_excessively_long_strip_is_rejected_before_inference(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "chatgpt_oauth")
    async def infer(*args, **kwargs):
        pytest.fail("Tile limit must be checked before spending model quota")
    monkeypatch.setattr(reader_vision.auth, "infer", infer)
    with pytest.raises(AuthError, match="too long"):
        asyncio.run(reader_vision.translate_image(Image.new("RGB", (350, 24000), "white")))
