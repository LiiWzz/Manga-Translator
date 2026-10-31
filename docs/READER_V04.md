# Manga Translator v0.4: Non-destructive Reader Mode

## ADR
The original image overlay corrupts some dialogue and artwork, especially stylized black/red bubbles. v0.4 makes a separate Chrome Side Panel the default. It never draws, removes or rewrites pixels. Legacy overlay code and endpoints remain for compatibility; the Reader uses the separate vision endpoint. Optional overlay is a possible v2 direction, subject to geometry and artwork-preservation evidence; see the [development roadmap](POC_PLAN.md).

## Workflow

1. Connect and pair the extension via Options, as before.
2. Open a manga webpage and click the extension toolbar button to open the Reader panel. Chrome opens it directly via `sidePanel.setPanelBehavior({openPanelOnActionClick: true})`, so the toolbar click is not delayed by any content-script injection. Clicking **แปลภาพที่เห็น** within the panel injects the read-only scanner. Reload the unpacked extension via `chrome://extensions` after pulling changes. If it still does not open, inspect the extension **Service worker** console and Chrome version/support for the Side Panel API.
3. Click **แปลภาพที่เห็น**. If prompted, click **อนุญาตเว็บไซต์** and approve Chrome's per-site access; then the extension discovers up to three loaded viewport images and sends them serially to the authenticated local endpoint.
4. Backend sends the image to the selected vision-capable model and validates complete source/Thai dialogue pairs. Tall strips are sent as overlapping crops in one request. Responses have no verified coordinates (`bbox` and `confidence` are `null`). Each image has a visible queued/loading/success/empty/error state. Errors stay on that image with **ลองใหม่**; retry sends only that failed image. The panel displays both texts; **แก้คำแปล** edits locally, **ไปยังภาพ** finds the source by image URL even if lazy loading has shifted its document index.
5. Scroll the page and click **แปลภาพที่เห็น** again. In-panel session results avoid sending the same image URL twice, including empty results. Failed images require explicit retry. **เริ่มใหม่** clears results and edits, stops the remaining queue and ignores late replies. Switching source tabs, changing the page URL (including its fragment), reloading or closing the source tab clears the page session and its context; click translate again to start on the new page.

## Safety / limitations

- No OpenAI tokens in extension storage; local pairing capability still required.
- Reader endpoint enforces the existing 8 MiB, 24 MP image bounds and extension auth. Context is bounded to 1500 characters. Caller text is treated as quoted context.
- Tall-strip input is limited to eight overlapping crops and 8 MiB of combined image data URLs. Inputs beyond those limits fail before inference. More crops can consume more model usage; no automatic retries are added.
- Results and edits last only for the current tab/page session and are not persisted or used to retrain AI. URL changes conservatively start a new session. Chapter changes inside an SPA that keeps the same URL cannot be identified generically; press **เริ่มใหม่** in that case. Persistent cache/edits are the next milestone.
- Reset/navigation stops new queued submissions and discards obsolete results; an inference already submitted may still complete and consume usage. This milestone does not cancel provider-side work.
- Retry context includes successful earlier images from this page, bounded to 1500 characters, and excludes later images. A correction is included when building context for subsequent requests.
- Three visible images are processed per click to keep latency and local gateway budgets bounded, not the whole chapter. Lazy-loaded pages require scrolling.
- Vision accuracy and reading order require human review. Avoiding duplicate dialogue across crop overlaps relies on the prompt; image fetch still uses configured host permissions.
- No crop-selection UI in this MVP. The optional later iteration can add user-selected crop regions with careful coordinate scaling.
- The user reported completing the Chrome Side Panel check on 2026-10-28; see the acceptance record below. PR review and merge approval remain separate.

## Troubleshooting: panel says เปิดหน้ามังงะก่อน
A Side Panel click is not a fresh `activeTab` grant. v0.4 now reads the active tab via the explicit `tabs` permission, reports inaccessible URLs, and requests the current website's host permission only after an explicit user action. Pull the branch and **Reload the unpacked extension** to activate new manifest permissions. Permission denial leaves the page unchanged. The Reader does not require broad automatic access to every website.

## v0.4 Vision-first quality correction
A real reader screenshot showed 79 individual OCR fragments (e.g. `my`, `A's`, `Ss`) for English dialogue inside a single balloon. This is a source-extraction failure, not a Thai word-wrap problem. The reader endpoint now sends the image directly to the selected **vision-capable** ChatGPT model via the existing Sign in with ChatGPT Responses API instead of Tesseract; it asks for one complete original-and-Thai pair per legible bubble, and rejects malformed output or untranslated English dialogue. No artificial bounding boxes are supplied, and the original page image is never modified.

**Model constraint:** A selected text-only model can reject image input; select a model that supports visual input in the local ChatGPT Settings. Vision calls may consume more of the account's usage allowance and may be slower. Automated mocked tests verify request shape, strict validation and API responses; they do **not** prove real vision model accuracy or entitlement. The user-reported Chrome check is recorded below; broader translation-quality evaluation remains a later milestone. Existing opened Reader panels may still show cached results until **เริ่มใหม่** or the extension is Reloaded.

## Latest accepted fix and next work

Matching punctuation-only balloons such as `......` and `?!` no longer invalidate otherwise valid Thai translations. Untranslated English, malformed output and invalid glyphs still fail validation. The reported 900 × 16000 strip previously shrank to 169 × 3000; it now uses six overlapping crops that preserve its 900-pixel width. The supplied image returned nine accepted entries, and the user accepted the fix. This does not establish quality across all manga or complete every manual acceptance check.

The Reader reliability feature branch implements the first milestone with mocked behavioral regressions and user-reported manual Chrome acceptance on 2026-10-28. Next work remains persistent cache/edits, translation-quality evaluation, selected-region translation and controlled continuous reading, in that order. [The roadmap](POC_PLAN.md) also records the tentative v2 overlay investigation separately from the historical v0.2 prototype. Additional brainstorming is saved in [the idea backlog](READER_IDEAS.md) without changing that order.

## Reliability acceptance

Automated: run `node --test apps/extension/test-reader-reliability.cjs` and the
existing wiring/syntax checks. Tests drive the real panel, content and worker
scripts with mocked Chrome APIs and generated dialogue, without inference usage.

2026-10-28 verification: 28 Reader behavior tests and all 70 mocked API tests
passed; JavaScript syntax, Side Panel wiring and manifest checks passed. A
BrowserOS neo preview using the real panel HTML/JS with mocked Chrome APIs also
confirmed persistent error display, no resubmission on repeat scan, retry of only
the failed image, and rejection of a late reply after reset. This preview does
not verify installed-extension permissions, service-worker lifecycle or real
Chrome Side Panel integration.

2026-10-28 manual acceptance: the user reported that the Chrome Side Panel check
was completed. This records the user's verification of the Reader implementation
at commit `8024581`; it does not claim that the agent independently ran installed
Chrome E2E or that every scenario below has an individually recorded result.
The browser-check blocker for PR #7 is cleared; code review, parent PRs and
explicit human merge approval remain separate. No merge is authorized by this
acceptance record.

Manual regression scenarios for future Reader changes:

1. Translate multiple permitted images with one failure. Confirm the error stays
   visible, scan does not resend existing results, and **ลองใหม่** retries only
   the failed image while keeping successful translations and edits.
2. Reset during a request, then start again. Confirm the old response never
   repopulates the panel or unlocks the new run's controls.
3. Switch tabs, change chapters/URL, reload and close the source tab during a
   request. Confirm queued work stops and the next session has no old context.
4. Reset or navigate while permissions/discovery are pending. Confirm no old
   request is submitted afterwards. Deny site permission and confirm the page is
   unchanged.
5. Insert a lazy-loaded image before an already translated image. Confirm
   **ไปยังภาพ** locates the original image and does not scroll a different chapter.
