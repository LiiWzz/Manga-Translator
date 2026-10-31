"""Normalize AI translations and reject unsupported glyphs before rasterization."""
from __future__ import annotations
import re
import unicodedata
from PIL import ImageFont

_INVALID = re.compile(r"[\uFFFD\u25A1\u25AF\u2610\uFFFC]")
_THAI = re.compile(r"[\u0e00-\u0e7f]")


def clean_translation(text: str) -> tuple[str, str | None]:
    if not isinstance(text, str):
        return "", "invalid_translation"
    text = unicodedata.normalize("NFC", text)
    text = "".join(c for c in text if unicodedata.category(c) not in {"Cc", "Cf", "Cs"}
                   or c in "\n\t")
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text or not _THAI.search(text):
        return text, "not_thai"
    if _INVALID.search(text):
        return text, "replacement_character_or_tofu"
    return text, None


def supports_text(font: ImageFont.FreeTypeFont, text: str) -> bool:
    """Best-effort glyph availability via FreeType charmap, not a visual guarantee."""
    try:
        from PIL import features
        import ctypes
        # Pillow provides FreeType charmap coverage through getmask2 errors only
        # for some builds. We explicitly reject known tofu/control characters.
        for c in text:
            if unicodedata.category(c) in {"Cc", "Cs"}:
                return False
        font.getmask(text)
        return True
    except (OSError, ValueError, TypeError):
        return False
