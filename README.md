# Manga Translator — Engineering POC v0.1

Chrome MV3 extension that detects manga images, OCRs English dialogue and overlays Thai text without changing original images.

## Quick start

Prerequisites: Docker (or Python 3.11+ with Tesseract OCR), Chrome.

```sh
docker compose up --build
```

API health: http://127.0.0.1:8000/health

Open `chrome://extensions`, enable Developer Mode, choose **Load unpacked**, and select `apps/extension`.
Browse an allowed page with image panels, then click the extension icon and **Translate visible images**.

Default translator is `mock` for a reproducible, zero-cost demonstration. To translate real text, copy `.env.example` to `.env`, configure `TRANSLATOR_PROVIDER=openai`, `OPENAI_API_KEY`, and optionally `OPENAI_MODEL`. Never put keys in extension source.

## Known limitations
- Best on English text in simple/white bubbles. No true inpainting.
- Requires image fetch access; CORS, access controls, and dynamic canvases can prevent processing.
- Images are sent to local backend only after user clicks translate; with configured cloud translation, OCR text is sent to the model provider.
- Initial version translates up to 3 images per click, and does not persist cache across browsing sessions.
- Popup-based translation works with normal web pages, not Chrome internal pages.
- Only use with material and sites you are authorized to access.

## Tests
```sh
cd apps/api && pip install -e '.[test]' && pytest -q
node --check ../extension/background.js
node --check ../extension/content.js
```

See [POC plan](docs/POC_PLAN.md) and [architecture](docs/ARCHITECTURE.md).