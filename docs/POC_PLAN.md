# Development Roadmap

Updated: 2026-10-28. This is the planning source of truth for upcoming work.

The [Reader idea backlog](READER_IDEAS.md) records the latest brainstorming for
later consideration. The user chose to retain the existing milestone order below;
the backlog does not expand or replace it.

## Current baseline: Vision + Reader Side Panel

The working POC translates English manga dialogue into Thai through the local
FastAPI gateway and displays source/translation pairs in a Chrome Side Panel.
Vision reads complete balloons; the Reader leaves the original page image intact.
Matching punctuation-only balloons are accepted, and tall strips use bounded,
overlapping crops in one inference request to preserve readable text.

The user has accepted the latest Reader fix after trying it. This is evidence for
that reading workflow, not completion of a broad quality or security benchmark.
Cache and edits currently last only for the current page session. The Reader
reliability feature branch adds per-image errors and retries, isolates context by
tab/page URL and discards obsolete work after reset or navigation. Automated
regressions cover these behaviors; real Chrome acceptance remains pending.
See [Reader behavior and limits](READER_V04.md).

## Next milestones

Implement in this order on feature branches in the Reader branch stack. Version
numbers and dates remain open until each milestone's scope is agreed.

| Priority | Scope | Acceptance evidence |
| --- | --- | --- |
| 1. Reader reliability | Persistent errors per image; explicit retry for failed images; context scoped to tab/chapter; stop queued work and discard late replies after reset or navigation. | Tests show failures remain visible, successful images are not resent, context stays within its chapter, and old replies cannot repopulate a reset panel. |
| 2. Persistent cache and edits | Store results and user corrections locally with size/expiry controls and a clear-data action. Invalidate on image content, model, prompt, glossary or relevant context changes. | Reopening resumes from valid saved results; changed inputs trigger translation; deletion removes saved dialogue. Credentials are excluded from cached results. |
| 3. Translation quality | Build an authorized sample set; review missing/duplicate balloons, reading order, Thai meaning/tone and consistent names. Add a per-story glossary. | Compare against the accepted baseline with human review and record coverage, duplicates, order and glossary adherence. Keep deterministic mocked regressions separate from live quality checks. |
| 4. Selected-region translation | Let the reader select a balloon or image section using verified original-image coordinates. | Selection stays aligned after scaling/scrolling and submits only the chosen region; artwork remains intact. |
| 5. Controlled continuous reading | Optional translation as new images appear, with pause, a bounded queue and request/usage controls. | Pausing stops new submissions; repeated images are reused; processing respects backend rate/concurrency limits. Measure latency and image/tile counts; report provider usage only when available. |

## Possible v2 direction: optional overlay

**Overlay may be explored for v2; it is a candidate, not a committed deliverable.**
Here, v2 means a possible future major version, distinct from the historical
[v0.2 overlay prototype](V02_ACCEPTANCE.md). Reader reliability and translation
quality come first; the Side Panel remains available if an overlay is pursued.

Before committing to overlay implementation, evaluate:

- Reliable balloon segmentation and text geometry. Current Vision Reader output
  has no verified bounding boxes and cannot directly position an overlay.
- English-text removal or inpainting that preserves artwork, including textured,
  dark and glowing balloons; unsafe regions must remain unchanged.
- Thai fonts, line breaking and fitting, with alignment on zoom, resize, scroll,
  CSS transforms and `object-fit`.
- An original/translated toggle, image-fetch constraints, latency and usage cost.

Use authorized images to compare original and composite at native resolution.
Record residual English, Thai overflow, misalignment and artwork damage. Proceed
only after human visual review establishes acceptable quality and cost.

## Delivery gates

- Keep each milestone reviewable in its own feature branch and PR; merge only
  after human approval. Review Chrome origin-permission changes explicitly.
- Add regression tests for fixes; run API tests with mock inference and extension
  syntax/wiring checks before proposing merge. Record manual Reader results.
- Use permitted image sources; exclude secrets and unlicensed manga assets from
  code, logs and fixtures. Preserve the existing image and usage limits.
- Keep deployment local to one operator. Resolve and re-review the outstanding
  [OAuth/security work](SECURITY_V031.md) before expanding distribution or access.
