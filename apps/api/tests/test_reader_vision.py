import asyncio
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
