# Manga Translator v0.4: Non-destructive Reader Mode

## ADR
The original image overlay corrupts some dialogue and artwork, especially stylized black/red bubbles. v0.4 makes a separate Chrome Side Panel the default. It never draws, removes or rewrites pixels. The v0.3 overlay implementation remains on its historical branch only.

## Workflow
1. Connect and pair the extension via Options, as before.
2. Open a manga webpage and click the extension toolbar button to open the Reader panel. Chrome opens it directly via `sidePanel.setPanelBehavior({openPanelOnActionClick: true})`, so the toolbar click is not delayed by any content-script injection. Clicking **แปลภาพที่เห็น** within the panel injects the read-only scanner. Reload the unpacked extension via `chrome://extensions` after pulling changes. If it still does not open, inspect the extension **Service worker** console and Chrome version/support for the Side Panel API.
3. Click **แปลภาพที่เห็น**. If prompted, click **อนุญาตเว็บไซต์** and approve Chrome's per-site access; then the extension discovers up to three loaded viewport images and sends them serially to the authenticated local endpoint.
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

## Troubleshooting: panel says เปิดหน้ามังงะก่อน
A Side Panel click is not a fresh `activeTab` grant. v0.4 now reads the active tab via the explicit `tabs` permission, reports inaccessible URLs, and requests the current website's host permission only after an explicit user action. Pull the branch and **Reload the unpacked extension** to activate new manifest permissions. Permission denial leaves the page unchanged. The Reader does not require broad automatic access to every website.
