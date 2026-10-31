# Reader idea backlog

Recorded: 2026-10-28. These are brainstorming notes, not implementation commitments.
The user asked to keep the ideas for later and follow the existing plan first.
[POC_PLAN.md](POC_PLAN.md) remains the planning source of truth; its milestone
order is unchanged.

## Product direction

A Thai manga reading companion that supports continuous reading, consistent
terminology and returning to an earlier reading session. Keep the Side Panel as
the main reading surface. Optional overlay remains a later experiment subject to
geometry, artwork-preservation and usage-cost evidence.

## Ideas to revisit

| Idea | Intended benefit | Notes for future evaluation |
| --- | --- | --- |
| Reliable reading | Visible image states and explicit retries without resubmitting successful images. | Already covered by roadmap milestone 1. |
| Resume reading | Save translations, user corrections and reading position locally. | Cache and edits are milestone 2; reading-position restoration is an additional candidate. |
| Per-story glossary | Consistent character names, factions, techniques and forms of address. | Glossary is milestone 3. Offer an explicit action to turn a correction into a glossary entry. |
| Structured story context | Track known characters, relationships and events rather than only trailing dialogue. | Use only previously read content; allow manual story/chapter selection before automatic detection. |
| Translation issue feedback | Let readers flag missing dialogue, wrong order, inconsistent names or awkward Thai. | Use authorized examples for evaluation; do not silently collect images or dialogue. |
| Distinguish unreadable from empty | Make skipped or incomplete dialogue visible and allow a selected crop retry. | Do not invent missing text, confidence scores or coordinates. Current empty results do not establish that an image has no text. |
| Per-story Thai style | Explore natural Thai, closer source phrasing and genre-specific language. | Preserve meaning and names; compare styles against the same reviewed sample set. |
| Selected-region translation | Translate or retry only a balloon or selected image section. | Already milestone 4; verify original-image coordinates. |
| Controlled continuous reading | Queue newly visible images with pause/resume and request bounds. | Already milestone 5; persistent cache comes first. |
| Measured usage display | Show queue size, reused images and latency. | Display provider usage only when available. Stopping new work does not guarantee cancellation of a submitted inference. |
| Optional overlay | Offer a translated-on-image view alongside the Reader. | Tentative v2 investigation only, not a committed deliverable. |

## Execution decision

Proceed with the existing milestones: **Reader reliability → persistent cache
and edits → translation quality → selected-region translation → controlled
continuous reading**. Revisit these ideas when defining the relevant milestone;
do not expand the first milestone to include persistence, glossary or overlay.
