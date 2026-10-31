"""OCR line detection, safe dialogue-block grouping and explainable diagnostics.

Geometric grouping is deliberately NOT claimed to be semantic balloon detection.
A background corridor check helps avoid merging text in adjacent balloons.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from collections import defaultdict

import numpy as np
import pytesseract
from PIL import Image
from .bubble_renderer import TextRegion


@dataclass
class OCRAnalysis:
    lines: list[TextRegion]
    groups: list[TextRegion]
    rejected: list[dict]


def _bbox_dict(region: TextRegion, index: int) -> dict:
    return {"index": index, "bbox": list(region.bbox),
            "source_text": region.source_text, "confidence": round(region.confidence, 3)}


def diagnostic_packet(analysis: OCRAnalysis) -> dict:
    return {"ocr_lines": [_bbox_dict(r, i) for i, r in enumerate(analysis.lines)],
            "groups": [_bbox_dict(r, i) for i, r in enumerate(analysis.groups)],
            "ocr_rejected": analysis.rejected}


def _background_corridor(image: Image.Image | None, upper: TextRegion,
                         lower: TextRegion) -> bool:
    """Reject a visible separator between stacked lines, when image is supplied."""
    if image is None:
        return True
    ax, ay, aw, ah = upper.bbox
    bx, by, bw, bh = lower.bbox
    start = ay + ah
    end = by
    if end - start < 3:
        return True
    left = max(ax, bx)
    right = min(ax + aw, bx + bw)
    if right - left < 5:
        return False
    # Inspect only the geometric separator; never depend on semantic OCR text.
    sample = np.asarray(image.crop((left, start, right, end)).convert("RGB"))
    if sample.size == 0:
        return False
    lum = sample.astype(np.float32).mean(axis=2)
    # A true light/dark flat corridor has no full-width contrasting row.
    light = np.mean(lum >= 180, axis=1)
    dark = np.mean(lum <= 65, axis=1)
    return bool(np.all((light >= .67) | (dark >= .67)))


def _related(a: TextRegion, b: TextRegion, image: Image.Image | None) -> bool:
    x, y, w, h = a.bbox
    bx, by, bw, bh = b.bbox
    if by < y:
        return _related(b, a, image)
    gap = by - (y + h)
    if gap < -min(h, bh) * .5 or gap > min(60, max(20, min(h, bh) * 1.8)):
        return False
    overlap = max(0, min(x + w, bx + bw) - max(x, bx))
    center_delta = abs(x + w / 2 - bx - bw / 2)
    if overlap < .22 * min(w, bw) or center_delta > max(65, max(w, bw) * .64):
        return False
    if max(w, bw) > 7 * min(w, bw) and center_delta > min(w, bw):
        return False
    if gap >= 3 and not _background_corridor(image, a, b):
        return False
    return True


def group_lines(lines: list[TextRegion], image: Image.Image | None = None) -> list[TextRegion]:
    """Merge top-to-bottom stacked text lines, not horizontally adjacent balloons."""
    ordered = sorted(lines, key=lambda r: (r.bbox[1], r.bbox[0]))
    n = len(ordered)
    parents = list(range(n))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for i, current in enumerate(ordered):
        for j in range(i + 1, n):
            nxt = ordered[j]
            if nxt.bbox[1] - current.bbox[1] > max(90, current.bbox[3] * 3):
                break
            if _related(current, nxt, image):
                # Don't merge a third balloon merely due to a transitive bridge.
                ri, rj = root(i), root(j)
                if ri != rj:
                    parents[rj] = ri

    buckets: dict[int, list[TextRegion]] = defaultdict(list)
    for i, region in enumerate(ordered):
        buckets[root(i)].append(region)
    grouped: list[TextRegion] = []
    for parts in buckets.values():
        parts.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
        x0 = min(p.bbox[0] for p in parts)
        y0 = min(p.bbox[1] for p in parts)
        x1 = max(p.bbox[0] + p.bbox[2] for p in parts)
        y1 = max(p.bbox[1] + p.bbox[3] for p in parts)
        grouped.append(TextRegion((x0, y0, x1-x0, y1-y0),
                       " ".join(p.source_text for p in parts),
                       min(p.confidence for p in parts)))
    return sorted(grouped, key=lambda r: (r.bbox[1], r.bbox[0]))


def analyze_regions(image: Image.Image) -> OCRAnalysis:
    data = pytesseract.image_to_data(image, lang="eng",
                 output_type=pytesseract.Output.DICT, config="--psm 11")
    lines: dict[tuple[int, int, int], list[tuple]] = defaultdict(list)
    rejected: list[dict] = []
    for i, raw in enumerate(data["text"]):
        text = (raw or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][i])
            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            key = (int(data["block_num"][i]), int(data["par_num"][i]),
                   int(data["line_num"][i]))
        except (ValueError, KeyError, TypeError):
            rejected.append({"reason": "malformed_ocr_word", "index": i})
            continue
        if confidence < 25 or w <= 0 or h <= 0:
            rejected.append({"reason": "low_confidence", "index": i,
                             "bbox": [x, y, w, h]})
            continue
        # Keep punctuation with dialogue, but skip pure decoration/symbol noise.
        if not re.search(r"[A-Za-z0-9]", text):
            rejected.append({"reason": "non_dialogue_symbol", "index": i,
                             "bbox": [x, y, w, h]})
            continue
        lines[key].append((text, x, y, w, h, confidence))
    found: list[TextRegion] = []
    for words in lines.values():
        words.sort(key=lambda p: p[1])
        text = " ".join(w[0] for w in words)
        confidence = sum(w[5] for w in words)/len(words)/100
        x0 = min(w[1] for w in words)
        y0 = min(w[2] for w in words)
        x1 = max(w[1]+w[3] for w in words)
        y1 = max(w[2]+w[4] for w in words)
        found.append(TextRegion((x0, y0, x1-x0, y1-y0), text, confidence))
    found.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    return OCRAnalysis(found, group_lines(found, image), rejected)


def extract_grouped_regions(image: Image.Image) -> list[TextRegion]:
    return analyze_regions(image).groups
