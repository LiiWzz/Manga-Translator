"""Manga Translator local-only POC v0.2."""
from __future__ import annotations

import io
import os

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile, Request, Depends, Form
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from .bubble_renderer import TextRegion, overlay_data_url, render_translations
from .ocr_grouping import extract_grouped_regions, analyze_regions, diagnostic_packet
from .oauth_routes import router as oauth_router
from .provider_adapter import translate_chatgpt
from .local_security import require_extension

app = FastAPI(title="Manga Translator POC v0.3")
app.include_router(oauth_router)
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


class RenderResponse(TranslateResponse):
    overlay_data_url: str
    applied_regions: int
    skipped: list[dict]
    render_mode: str = "safe-flat-block-overlay"
    diagnostics: dict | None = None


def extract_regions(image: Image.Image):
    return [(list(r.bbox), r.source_text, r.confidence) for r in extract_grouped_regions(image)]


async def translate_texts(texts: list[str], context: str = "") -> list[str]:
    provider = os.getenv("TRANSLATOR_PROVIDER", "chatgpt_oauth").lower()
    if provider == "chatgpt_oauth":
        return await translate_chatgpt(texts, context=context) if context else await translate_chatgpt(texts)
    if provider == "mock":
        return ["[TH DEMO] " + text for text in texts]
    if provider != "openai":
        raise HTTPException(status_code=500, detail="Unknown translator provider")
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
    if not texts:
        return []
    import json
    prompt = ("Translate each English manga dialogue into fluent, concise, natural Thai, "
              "preserving speaker names and line order. Return a JSON object with a "
              "translations array of Thai strings only, one item per input. Input:\n"
              + json.dumps(texts, ensure_ascii=False))
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer "+key},
                json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "system", "content": "Return strictly JSON with translations array."},
                                   {"role": "user", "content": prompt}]},
            )
            response.raise_for_status()
            values = json.loads(response.json()["choices"][0]["message"]["content"])["translations"]
            if not isinstance(values,list) or len(values)!=len(texts) or not all(isinstance(v,str) for v in values):
                raise ValueError("Translation response has wrong shape")
            return values
    except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
        raise HTTPException(status_code=502,detail="Translation provider failed") from exc


async def _decode_image(file: UploadFile) -> Image.Image:
    if file.content_type not in {"image/png","image/jpeg","image/webp"}:
        raise HTTPException(status_code=415,detail="Unsupported MIME type")
    raw = await file.read(MAX_IMAGE_BYTES+1)
    if len(raw)>MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413,detail="Image exceeds size limit")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>MAX_PIXELS:
                raise HTTPException(status_code=413,detail="Image exceeds pixel limit")
            if source.format not in {"PNG","JPEG","WEBP"}:
                raise HTTPException(status_code=415,detail="Unsupported image format")
            return ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400,detail="Invalid image") from exc


async def _process(file: UploadFile, debug: bool = False):
    image = await _decode_image(file)
    try:
        analysis = analyze_regions(image) if debug else None
        source = ([(list(r.bbox), r.source_text, r.confidence) for r in analysis.groups]
                  if analysis is not None else extract_regions(image))
    except Exception as exc:
        raise HTTPException(status_code=503,detail="OCR unavailable") from exc
    translated = await translate_texts([txt for _,txt,_ in source])
    regions = [Region(bbox=box,source_text=txt,translated_text=translation,confidence=confidence)
               for (box,txt,confidence),translation in zip(source,translated)]
    return image,source,translated,regions,analysis


@app.get("/health")
def health():
    return {"status":"ok","provider":os.getenv("TRANSLATOR_PROVIDER","chatgpt_oauth")}


@app.post("/api/v1/translate",response_model=TranslateResponse)
async def translate(file: UploadFile = File(...), gate=Depends(require_extension)):
    image,_,_,regions,_ = await _process(file)
    return TranslateResponse(image_width=image.width,image_height=image.height,regions=regions,
                             provider=os.getenv("TRANSLATOR_PROVIDER","chatgpt_oauth"))


@app.post("/api/v1/translate-rendered",response_model=RenderResponse)
async def translate_rendered(file: UploadFile = File(...), debug: bool = False, gate=Depends(require_extension)):
    image,source,translations,regions,analysis = await _process(file, debug=debug)
    try:
        overlay,applied,skipped = render_translations(
            image,[TextRegion(tuple(box),txt,confidence) for box,txt,confidence in source],translations)
    except RuntimeError as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    diagnostic = diagnostic_packet(analysis) if analysis is not None else None
    if diagnostic is not None:
        diagnostic["skipped"] = skipped
    return RenderResponse(image_width=image.width,image_height=image.height,regions=regions,
                          provider=os.getenv("TRANSLATOR_PROVIDER","chatgpt_oauth"),
                          overlay_data_url=overlay_data_url(overlay),
                          applied_regions=applied,skipped=skipped,diagnostics=diagnostic)


@app.post("/api/v1/reader/translate")
async def reader_translate(file: UploadFile = File(...), context: str = Form(""), gate=Depends(require_extension)):
    """Non-destructive reader response. OCR and translations only, no overlay."""
    if len(context) > 1500:
        raise HTTPException(status_code=422, detail="Context exceeds 1500 characters")
    image = await _decode_image(file)
    try:
        from fastapi.concurrency import run_in_threadpool
        source = await run_in_threadpool(extract_regions, image)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="OCR unavailable") from exc
    translations = await translate_texts([txt for _, txt, _ in source], context=context)
    if len(translations) != len(source):
        raise HTTPException(status_code=502, detail="Translation count mismatch")
    return TranslateResponse(
        image_width=image.width, image_height=image.height,
        regions=[Region(bbox=box, source_text=txt, translated_text=translated,
                        confidence=confidence)
                 for (box, txt, confidence), translated in zip(source, translations)],
        provider=os.getenv("TRANSLATOR_PROVIDER", "chatgpt_oauth"))
