# Manga Translator — Bubble-aware POC v0.2

Chrome MV3 extension: translate English manga dialogue to Thai within flat dark/light speech balloons, without white HTML boxes or altering the original source image.

## Quick start

```sh
git checkout feat/bubble-aware-rendering-v0.2
docker compose up --build -d
curl http://127.0.0.1:8000/health
```

Open `chrome://extensions` → Developer Mode → Load unpacked → choose `apps/extension`. **Reload the extension after pulling updates** and refresh the reader page. Click the toolbar icon; the first 3 eligible visible images will be processed.

### Real translation setup

The default `mock` provider is intentionally *not Thai translation*; v0.2 will not paint English demo strings onto the artwork. To enable Thai:

```sh
cp .env.example .env
# Set TRANSLATOR_PROVIDER=openai and OPENAI_API_KEY=<your secret>
docker compose up --build -d --force-recreate
```

Never store API keys in extension code or Git. Browser image bytes are transmitted to your local backend when you click translate. With OpenAI mode, OCR text is sent to the cloud service.

### Tests

```sh
cd apps/api && pip install -e '.[test]' && pytest -q
node --check ../extension/background.js
node --check ../extension/content.js
```

See [Acceptance Contract](docs/V02_ACCEPTANCE.md), [Architecture](docs/ARCHITECTURE.md), and [CDN Troubleshooting](docs/CORS_TROUBLESHOOTING.md).

**Limitations:** Flat monochrome balloons only. Decorative or textured dialogue may be skipped. This is not learned bubble segmentation or AI inpainting. The unprotected local demo API is not production ready. Only access material/sites you are authorized to use.
