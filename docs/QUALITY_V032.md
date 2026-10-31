# v0.3.2 quality remediation / evidence contract

This iteration addresses real user screenshots: English surviving under Thai, overlapping typography, replacement-box glyphs, and stylized black/red dialogue.

## Implemented
- OCR lines are grouped conservatively with block geometry and image-backed corridor checks. This is not trained balloon segmentation and may under/over-group.
- Renderer normalizes Thai text, rejects known missing-character/tofu symbols, checks font viability and only erases the full verified uniform layout box. Textured areas and unverified glow/artwork remain unchanged.
- `?debug=true` on the authenticated translate-rendered endpoint returns `diagnostics`: `ocr_lines`, `groups`, `ocr_rejected`, and `skipped`. The extension Options **Show OCR and skipped-region debug boxes** toggle requests that payload and overlays colored bounding boxes: green for applied, red for skipped. This never includes OpenAI tokens.
- Regression tests cover stacked dialogue, distinct side-by-side bubbles, Unicode issues, rendering safety and debug shapes.

## Design boundary
**Do not blank a whole irregular dark/red-glow balloon automatically.** Current POC can replace only a safe uniform interior, otherwise records `textured_or_unknown_background` / `layout_not_inside_uniform_bubble`. A proper manga-specific segmentation/inpainting engine is still required to erase all stylized English without affecting art. Do not advertise 100% translation coverage.

## Manual image acceptance criteria
For each consented sample, compare original, debug regions, translation and final composite at 100% resolution; count OCR recall, word translation coverage, skipped reasons, old English remnants, tofu glyphs, word-wrap overflow and artwork damage. Four user-supplied screenshots are useful as human visual examples; not included in the repository to avoid unverified redistribution.

## Operational limitations
- Debug output includes original dialogue; use only on your own local loopback installation.
- Server Rate Limit = 12 requests/min; extension paced queue continues working on lazy-loaded images as they appear.
- 8 MiB / 24 MP image ceilings; unsupported CDN permissions and unusual image elements can still prevent full-page translation.
- The self-review is not independent agent validation. Actual Chrome/Safari E2E and a human manga-quality review still block merge.
