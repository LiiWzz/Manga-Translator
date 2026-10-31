"""Conservative replacement of English text inside flat black/white bubbles.

Not AI inpainting. Unknown/textured regions remain untouched rather than
risking damage to the underlying manga artwork.
"""
from __future__ import annotations

import base64
import io
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    os.environ.get("THAI_FONT_PATH", ""),
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThaiUI-Regular.ttf",
    "/usr/share/fonts/truetype/tlwg/Sawasdee.ttf",
)


@dataclass(frozen=True)
class TextRegion:
    bbox: tuple[int, int, int, int]
    source_text: str
    confidence: float = 1.0


def _tone(image: np.ndarray, bbox: tuple[int, int, int, int]):
    ih, iw = image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, x - 5), max(0, y - 5)
    x1, y1 = min(iw, x + w + 5), min(ih, y + h + 5)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = image[y0:y1, x0:x1].astype(np.float32)
    lum = np.mean(patch, axis=2)
    dark, light = lum <= 85, lum >= 170
    count = patch.shape[0] * patch.shape[1]
    if dark.sum() >= count * .56:
        pixels, fg = patch[dark], (255, 255, 255)
    elif light.sum() >= count * .56:
        pixels, fg = patch[light], (15, 15, 15)
    else:
        return None
    if np.max(np.std(pixels, axis=0)) > 17:
        return None
    return tuple(int(round(float(v))) for v in np.median(pixels, axis=0)), fg


def _thai_clusters(text: str) -> list[str]:
    clusters = []
    for char in text:
        if clusters and (unicodedata.combining(char) or unicodedata.category(char).startswith("M")):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, current = [], ""
    for part in re.findall(r"\S+\s*", text.strip()):
        candidate = (current + part).strip()
        if current and font.getlength(candidate) > width:
            lines.append(current.rstrip())
            current = ""
        if font.getlength(part.strip()) <= width:
            current += part
            continue
        for cluster in _thai_clusters(part):
            trial = current + cluster
            if current and font.getlength(trial.strip()) > width:
                lines.append(current.strip())
                current = cluster
            else:
                current = trial
    if current.strip():
        lines.append(current.strip())
    return lines


def _fit(text: str, width: int, height: int, path: str):
    for size in range(min(48, max(13, height)), 9, -1):
        font = ImageFont.truetype(path, size=size)
        lines = _wrap(text, font, max(15, width - 8))
        spacing = max(2, int(size * .18))
        ascent, descent = font.getmetrics()
        lh = ascent + descent
        if lines and len(lines) * lh + (len(lines)-1) * spacing <= height - 4:
            return font, lines, spacing, lh
    return None


def render_translations(image: Image.Image, regions: list[TextRegion], translations: list[str]):
    """Return (transparent overlay, applied count, skipped reasons).

    The input image remains untouched. A flat-color text region is painted with
    a matching sampled background and Thai lettering. Textured regions are
    skipped; this deliberately does not invent lost artwork.
    """
    if len(regions) != len(translations):
        raise ValueError("Translation count mismatch")
    path = next((p for p in FONT_CANDIDATES if p and Path(p).is_file()), None)
    if not path:
        raise RuntimeError("Thai font missing: configure THAI_FONT_PATH")
    rgb = np.asarray(image.convert("RGB"))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    applied, skipped = 0, []
    for index, (region, text) in enumerate(zip(regions, translations)):
        x, y, w, h = region.bbox
        if not text or not re.search(r"[\u0E00-\u0E7F]", text):
            skipped.append({"index": index, "reason": "not_thai"})
            continue
        if w < 12 or h < 9 or x < 0 or y < 0 or x+w > image.width or y+h > image.height:
            skipped.append({"index": index, "reason": "invalid_bbox"})
            continue
        result = _tone(rgb, region.bbox)
        if not result:
            skipped.append({"index": index, "reason": "textured_or_unknown_background"})
            continue
        bg, fg = result
        x0, y0 = max(0, x-3), max(0, y-3)
        x1, y1 = min(image.width, x+w+3), min(image.height, y+h+3)
        dest_h = max(h+12, int(h*1.4))
        dest_w = min(image.width-x0, max(w+10, int(w*1.22)))
        tx = max(0, x+w//2-dest_w//2)
        ty = max(0, y+h//2-dest_h//2)
        dest_w = min(dest_w, image.width-tx)
        dest_h = min(dest_h, image.height-ty)
        fit = _fit(text, dest_w, dest_h, path)
        if fit is None:
            skipped.append({"index": index, "reason": "text_does_not_fit"})
            continue
        other = _tone(rgb, (tx, ty, dest_w, dest_h))
        if not other or max(abs(a-b) for a, b in zip(bg, other[0])) > 18:
            skipped.append({"index": index, "reason": "layout_not_inside_uniform_bubble"})
            continue
        font, lines, spacing, lh = fit
        draw.rectangle((x0, y0, x1, y1), fill=(*bg, 255))
        total = len(lines)*lh+(len(lines)-1)*spacing
        top = ty+max(0,(dest_h-total)//2)
        for line in lines:
            left = tx+(dest_w-font.getlength(line))/2
            draw.text((left,top), line, font=font, fill=(*fg,255), anchor="lt")
            top += lh+spacing
        applied += 1
    return overlay, applied, skipped


def overlay_data_url(overlay: Image.Image) -> str:
    stream = io.BytesIO()
    overlay.save(stream, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
