# v0.2 Acceptance Contract — Thai In-Bubble Rendering

## Goal
Replace English dialogue *inside the original speech balloon* without white rectangle widgets or modifying the underlying downloaded source image.

## v0.2 behavior
- Backend detects text with Tesseract and groups nearby lines conservatively.
- On flat black or white backgrounds only, sampled dominant background color covers the English OCR bounding box.
- Thai is rendered via Noto Thai font into the same area using transparent PNG patches.
- Content script aligns the transparent image overlay with the source image on scroll/resize. The original source is preserved.
- Original artwork/text remains untouched if confidence in background uniformity or layout is insufficient.
- If TRANSLATOR_PROVIDER=mock, no fake 'Thai' is placed on artwork. Real translation requires server-side credentials.

## Non-goals / known shortcomings
- **Not a semantic balloon detector**: Tesseract line grouping is heuristic and still may miss/skew/merge speech balloons.
- **Not general-purpose inpainting**: artwork behind lettering, gradients, and complex textured lettering are not reconstructed.
- Thai wrap uses character clusters, not dictionary-based Thai sentence breaking; typography needs editorial QA.
- Flat-area approximation can still create small block edges where background color changes.
- Raster overlay may misalign on CSS transforms/object-fit/canvas-based readers.
- No automatic scroll translation, no persistent cache, no original/translated toggle.
- CDN access limitations remain; no bypass of 401/403/anti-hotlinking systems.

## Gates
- [x] Unit/API tests run locally against synthetic monochrome speech balloon fixtures.
- [x] Mock mode must leave the image untouched.
- [x] Irregular backgrounds must fail closed.
- [ ] Manually inspect pixel-level preservation on authorized real manga images.
- [ ] Browser E2E test with authorized image hosting.
- [ ] Measure OCR recall, Thai fit rate, overlay misalignment, and latency.
- [ ] Confirm CI on the PR.

## How to test
```sh
git checkout feat/bubble-aware-rendering-v0.2
docker compose up --build -d
curl http://127.0.0.1:8000/health
```
Set TRANSLATOR_PROVIDER=openai and OPENAI_API_KEY in .env for actual Thai text, restart Docker. Reload unpacked apps/extension at chrome://extensions, reload manga page, click the extension icon. Inspect Extension Service Worker logs and Backend logs. For broken or complex balloons the system deliberately skips repainting; this is not considered successful translation.
