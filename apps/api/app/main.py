"""Manga Translator POC API. Do not expose this unauthenticated demo on public internet."""
import io
import os
import re
from typing import Literal

import httpx
import pytesseract
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

app = FastAPI(title="Manga Translator POC")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 24_000_000


class Region(BaseModel):
    bbox: list[int]
    source_text: str
    translated_text: str
    confidence: float


class TranslateResponse(BaseModel):
    image_width: int
    image_height: int
    regions: list[Region]
    provider: str


def extract_regions(image: Image.Image) -> list[tuple[list[int], str, float]]:
    """Group Tesseract words by paragraph/block and produce bounding boxes."""
    data = pytesseract.image_to_data(image, lang="eng", output_type=pytesseract.Output.DICT)
    groups = {}
    for i, raw in enumerate(data["text"]):
        word = (raw or "").strip()
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            continue
        if not word or conf < 25:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append((word, int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i]), conf))
    regions = []
    for words in groups.values():
        text = " ".join(w[0] for w in words)
        x1 = min(w[1] for w in words)
        y1 = min(w[2] for w in words)
        x2 = max(w[1] + w[3] for w in words)
        y2 = max(w[2] + w[4] for w in words)
        regions.append(([x1, y1, x2 - x1, y2 - y1], text, sum(w[5] for w in words) / len(words) / 100))
    return sorted(regions, key=lambda r: (r[0][1], r[0][0]))


async def translate_texts(texts: list[str]) -> list[str]:
    provider = os.getenv("TRANSLATOR_PROVIDER", "mock").lower()
    if provider == "mock":
        return ["[TH DEMO] " + text for text in texts]
    if provider != "openai":
        raise HTTPException(status_code=500, detail="Unknown translator provider")
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
    if not texts:
        return []
    prompt = "Translate these English manga dialogue lines into natural Thai. Return ONLY a JSON array of strings in the same order, one translation per input. Preserve names and punctuation.\n" + __import__("json").dumps(texts, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0, "response_format": {"type": "json_object"}, "messages": [
                    {"role": "system", "content": "Return a JSON object with a translations array containing Thai strings only."},
                    {"role": "user", "content": prompt},
                ]},
            )
            response.raise_for_status()
            payload = response.json()["choices"][0]["message"]["content"]
            parsed = __import__("json").loads(payload)
            result = parsed["translations"]
            if len(result) != len(texts) or any(not isinstance(t, str) for t in result):
                raise ValueError("Translation count mismatch")
            return result
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Translation provider failed") from exc


@app.get("/health")
def health():
    return {"status": "ok", "provider": os.getenv("TRANSLATOR_PROVIDER", "mock")}


@app.post("/api/v1/translate", response_model=TranslateResponse)
async def translate(file: UploadFile = File(...)):
    if file.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=415, detail="Unsupported image MIME type")
    raw = await file.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise HTTPException(status_code=413, detail="Too many pixels")
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise HTTPException(status_code=415, detail="Unsupported image format")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail="Invalid image") from exc
    try:
        regions = extract_regions(image)
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError) as exc:
        raise HTTPException(status_code=503, detail="OCR unavailable") from exc
    translated = await translate_texts([text for _, text, _ in regions])
    return TranslateResponse(
        image_width=image.width,
        image_height=image.height,
        regions=[Region(bbox=box, source_text=txt, translated_text=translation, confidence=confidence)
                 for (box, txt, confidence), translation in zip(regions, translated)],
        provider=os.getenv("TRANSLATOR_PROVIDER", "mock"),
    )
