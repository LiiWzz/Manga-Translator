# Manga Translator v0.4: Non-destructive Reader Mode

## ADR
The original image overlay corrupts some dialogue and artwork, especially stylized black/red bubbles. v0.4 makes a separate Chrome Side Panel the default. It never draws, removes or rewrites pixels. The v0.3 overlay implementation remains on its historical branch only.

## Workflow
1. Connect and pair the extension via Options, as before.
2. Open a manga webpage and click the extension toolbar button to open the Reader panel.
3. Click **แปลภาพที่เห็น**; extension discovers up to three loaded viewport images and sends them serially to the authenticated local endpoint.
4. Backend runs OCR, translates a batch of regions, and returns originals, Thai translations and coordinates. Panel displays both; **แก้คำแปล** edits locally, **ไปยังภาพ** scrolls to the source image.
5. Scroll the page and click **แปลภาพที่เห็น** again. In-panel session cache avoids sending the same image URL twice. **เริ่มใหม่** clears the panel and cache.

## Safety / limitations
- No OpenAI tokens in extension storage; local pairing capability still required.
- Reader endpoint enforces the existing 8 MiB, 24 MP image bounds and extension auth. Context is bounded to 1500 characters. Caller text is treated as quoted context.
- Cache is per panel lifetime, keyed by tab and image URL; edits are not persisted and do not retrain AI.
- Three visible images are processed per click to keep latency and local gateway budgets bounded, not the whole chapter. Lazy-loaded pages require scrolling.
- OCR accuracy and reading order remain heuristic; image fetch still uses configured host permissions.
- No crop-selection UI in this MVP. The optional later iteration can add user-selected crop regions with careful coordinate scaling.
- Real Chrome Side Panel E2E must be run manually before moving this PR out of Draft.
