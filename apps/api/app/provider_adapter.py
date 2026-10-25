"""Glue between existing OCR pipeline and ChatGPT plan translation."""
import json
from fastapi import HTTPException

from .siwc import AuthError, auth


async def translate_chatgpt(texts: list[str]) -> list[str]:
    try:
        return await auth.translate(texts)
    except AuthError as exc:
        # The error's description has no user token data.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
