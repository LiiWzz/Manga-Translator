# Persistent Reader cache and edits

The second roadmap milestone saves successful and empty Reader results in
`chrome.storage.local`. Press **แปลภาพที่เห็น** after reopening the panel to
revalidate visible images and restore matching saved translations and corrections.
The gateway must be reachable and the extension paired even for reuse.

## Install and try

Update the local gateway (`docker compose up --build -d api`), reload the unpacked
extension in `chrome://extensions`, and refresh the permitted manga page. The
new extension needs the authenticated `/api/v1/reader/profile` endpoint.

1. Translate a visible image and use **แก้คำแปล → บันทึก**. Save reports success
   only after local storage acknowledges it. A failed save leaves the editor
   open; **ยกเลิก** discards an unsaved edit.
2. Close/reopen the panel, then translate the same visible images. Matching
   results show **ใช้คำแปลที่บันทึกไว้**, including saved corrections, without
   another inference request.
3. **เริ่มใหม่** clears the panel and current context, retaining durable data.
   **ลบคำแปลที่บันทึกไว้** deletes all saved Reader results and corrections across
   pages in this Chrome profile and resets open Reader panels. It preserves
   pairing and other extension preferences.

## Validity and context

The worker fetches current image bytes with HTTP caching disabled, using the
existing host/MIME/size/redirect restrictions. It hashes the bytes and a canonical
identity containing the exact page URL, the bounded context actually submitted,
the cache schema version, and the gateway's opaque translation fingerprint.
Raw image bytes, URLs, context and credentials are not persisted in cache records.

The fingerprint includes the selected model, account identity, Vision instructions,
image/crop limits and explicit pipeline/glossary revisions. Token refresh alone
does not invalidate dialogue. The glossary revision is currently `none`; no
glossary editor or glossary application is implemented in this milestone.
Maintainers must bump `READER_PIPELINE_VERSION` when changing other prompt-building,
preprocessing or validation behavior, and incorporate the applied glossary identity
when implementing that future milestone.

Every scan revalidates visible successful/empty images; it may download images
and query the gateway again, but only a cache miss submits inference. Failed
images still require explicit retry. The profile endpoint authenticates the local
capability without consuming translation admission slots. Translation rate and
concurrency limits are unchanged. The POST checks the expected fingerprint before
inference and again afterwards; settings changes return HTTP 409 without saving
the mismatched result.

Context is rebuilt from successful earlier images in the current page session,
including their saved corrections. A changed earlier correction invalidates
downstream results when that context changes. If the panel is reopened farther
down the page without the earlier images in its session, the context differs and
the worker conservatively translates again. This milestone does not restore
reading position or reconstruct an entire chapter. Reuse also requires that the
image can still be fetched; it is not an offline reading mode.

## Storage lifecycle

- Keep at most 200 entries and 4 MiB of serialized UTF-8 Reader payload, leaving
  headroom for the existing pairing/preferences storage. Evict least recently
  used entries when either bound is exceeded.
- Expire results and their corrections seven days after original creation;
  reads and edits do not extend that expiry. Expired entries are physically
  removed on the next cache operation, not by a background timer.
- Retain original dialogue and user corrections separately. Only whitelisted
  dialogue fields and opaque keys are stored. No image assets or OAuth tokens
  are stored; edits do not train the model.
- Only the service worker writes the cache namespace. Storage access is restricted
  to trusted extension contexts using [Chrome's storage access-level API](https://developer.chrome.com/docs/extensions/reference/api/storage#method-StorageArea-setAccessLevel).
  Reader mutation messages require the actual extension Reader page as sender.
- Serialize storage operations. Clear-data rotates a persisted epoch so pending
  translations or edits cannot restore deleted dialogue, including across worker
  restart. A concurrent duplicate translation cannot overwrite a saved correction.
- If storage is unavailable/full, successful translation remains visible with a
  persistence warning. Do not claim an edit was saved when its write failed.

## Verification

- `node apps/extension/test-sidepanel-wiring.cjs`: wiring plus 54 behavior/cache
  regressions, including panel/worker restart, exact-input invalidation, expiry,
  byte/entry bounds, quota failures, unsaved editors and clear-data races.
- Mocked API suite: 84 passed. Covers authenticated metadata, no credential
  disclosure, profile invalidation and changes during inference. Existing
  translation/security regressions continue to pass.
- BrowserOS neo preview with real panel/worker/cache scripts and mocked Chrome
  APIs: saved an edited translation, reloaded the page and restored it with the
  inference count unchanged at one; clear-data removed all entries, and the next
  scan produced a fresh translation with inference count two.
- The preview uses generated data and a localStorage-backed Chrome API shim.
  It does not establish installed-extension storage/service-worker behavior.
  Keep this cache milestone's PR Draft until actual Chrome acceptance.

Manual acceptance for this milestone: repeat the install/try steps in Chrome;
restart the extension/service worker; change model and an upstream correction;
clear while a request is pending; confirm pairing is retained. Permission/origin
scope and website access rules are unchanged. The user's earlier Chrome check
applies to the reliability baseline, not this new persistence implementation.
