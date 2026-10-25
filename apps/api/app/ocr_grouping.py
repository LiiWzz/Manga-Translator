"""Conservative Tesseract line grouping; not semantic balloon detection."""
from __future__ import annotations

import pytesseract
from PIL import Image
from .bubble_renderer import TextRegion


def extract_grouped_regions(image: Image.Image) -> list[TextRegion]:
    data = pytesseract.image_to_data(image, lang="eng", output_type=pytesseract.Output.DICT, config="--psm 11")
    lines = {}
    for i, raw in enumerate(data["text"]):
        word = (raw or "").strip()
        try:
            confidence = float(data["conf"][i])
        except (ValueError, TypeError):
            continue
        if not word or confidence < 35:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append((word, int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i]), confidence))
    regions = []
    for words in lines.values():
        text = " ".join(w[0] for w in words)
        confidence = sum(w[5] for w in words)/len(words)/100
        letters = sum(ch.isalpha() for ch in text)
        if letters == 0 or (letters < 2 and confidence < .88):
            continue
        x0 = min(w[1] for w in words)
        y0 = min(w[2] for w in words)
        x1 = max(w[1]+w[3] for w in words)
        y1 = max(w[2]+w[4] for w in words)
        regions.append(TextRegion((x0,y0,x1-x0,y1-y0),text,confidence))
    regions.sort(key=lambda r: (r.bbox[1],r.bbox[0]))
    grouped = []
    for region in regions:
        if not grouped:
            grouped.append(region)
            continue
        previous = grouped[-1]
        px,py,pw,ph = previous.bbox
        x,y,w,h = region.bbox
        gap = y-(py+ph)
        centers = abs((px+pw/2)-(x+w/2))
        overlap = max(0,min(px+pw,x+w)-max(px,x))
        related = centers <= max(38,min(pw,w)*.62) or overlap >= min(pw,w)*.35
        if 0 <= gap <= max(24,min(ph,h)*1.4) and related:
            nx,ny = min(px,x),min(py,y)
            nr,nb = max(px+pw,x+w),max(py+ph,y+h)
            grouped[-1] = TextRegion((nx,ny,nr-nx,nb-ny),previous.source_text+" "+region.source_text,min(previous.confidence,region.confidence))
        else:
            grouped.append(region)
    return grouped
