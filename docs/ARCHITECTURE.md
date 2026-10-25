# Architecture Decisions

Browser: minimal Chrome MV3 click-to-translate. Content script discovers visible images and renders overlays. Background service worker fetches accessible image bytes and calls localhost API.

Backend: FastAPI + Tesseract baseline; optional OpenAI text translation. No cloud keys in Chrome.

Trade-offs:
- Original artwork remains unchanged; white rectangle overlays are a functional prototype, not inpainting.
- Word grouping by OCR line may fragment balloons.
- Cross-origin manga CDNs can reject service-worker image fetches, even when displayed on webpage.
- Large images consume OCR CPU. The server enforces byte and pixel limits.
- Do not deploy the unauthenticated demo publicly.
- Follow-up: site adapters, OCR benchmarks, reading-order detection, batch context, cancellation, caching and retries.
