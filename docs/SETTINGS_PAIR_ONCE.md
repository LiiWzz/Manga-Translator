# Settings: pair once

Implementation plan, 2026-10-28. This work is stacked on the Reader panel branch;
the Reader roadmap order is unchanged.

## User journey

1. Start the existing local gateway. In the terminal run
   `docker compose exec api python -m app.local_security pair`.
2. Enter the short-lived code in Extension Settings and explicitly allow this
   extension to translate and manage the local ChatGPT connection.
3. Open connection settings from the extension, connect ChatGPT and select an
   available model from a dropdown. No model slug copying or normal admin-key
   entry is required.
4. Return to Settings to see gateway, pairing, account permission and selected
   model state. Refresh on focus without submitting inference.

## Implementation steps

- [x] Add local CLI pairing with explicit management consent and separate reader
  and management credentials. Preserve legacy reader-only pairing.
- [x] Exchange the management credential for a short-lived, single-use session
  ticket. POST the ticket from an extension launch page; never put credentials
  or tickets in URLs. Keep HttpOnly sessions, CSRF and Host/Origin checks.
- [x] Bind management browser sessions and tickets to the current pairing so
  re-pair/revoke also invalidates previously opened management sessions.
- [x] Replace raw JSON and equal-weight actions with Thai status, next steps,
  inline errors, model selection and advanced/recovery sections.
- [x] Cover consent, expiry/replay, origin checks, revocation, old credentials,
  storage/network failure and UI state with deterministic tests.
- [x] Run the mocked API suite, JS syntax and extension regressions; inspect
  generated-data UI in BrowserOS neo.

Delivery: a Draft PR stacked on Reader panel PR #9; never merge automatically.

## Security and recovery

The terminal is the initial owner authorization boundary. Generating a code does
not revoke existing pairing; redeeming a new code replaces the single paired
extension. Codes expire after ten minutes. Management credentials remain inside
trusted extension storage and never contain OpenAI credentials. Existing
translation credentials do not gain management authority.

Remembered management authority means access to this trusted extension profile
can manage the local account connection. This is an explicit grant during
pairing. The POC remains local, single-user and single-worker. CLI `pair` is the
recovery path after reinstall or loss of browser storage. Legacy admin unlock is
retained under recovery during migration.

Provider model metadata does not establish vision support; show a clear hint
without inventing a compatibility badge. Status checks do not prove inference
works or consume a test translation. Real Chrome/OAuth acceptance remains a
separate check from mocked tests and browser previews.


## Session handoff

The extension stores distinct opaque `mangaCapability` (Reader) and
`mangaSettingsCapability` (management) values in trusted `chrome.storage.local`.
The backend persists only their hashes in one capability record. Reader-only
legacy codes remain reader-only even if a client requests management authority.

Opening management launches an extension-owned tab, which exchanges its
management bearer at `/api/v1/settings/ticket` for a one-use ticket (60-second
expiry, at most 32 pending). The backend keeps a hash of the ticket and binds it
to the issuing extension origin and pairing generation. The launch page POSTs
it to `/auth/extension-session`; neither bearer nor ticket goes into a URL.
The handoff rotates the browser session and establishes an HttpOnly, SameSite=Lax
cookie. All owner mutations still require same-origin context and session CSRF.
The launch page uses an origin-only referrer policy to retain its form POST
Origin; OAuth callbacks and sensitive responses keep `no-referrer`.

Pair-issued browser sessions expire after 30 minutes and do not survive gateway
restart. Reopening from the paired extension creates a fresh session without
another code. Re-pair/revoke invalidates its old credentials, tickets and browser
sessions on subsequent requests. Existing admin-key recovery sessions retain
legacy behavior; resetting an admin key still requires restarting the API.

Unpair first revokes backend authority, then forgets both local credentials.
If the backend cannot be reached, local-only forgetting is a separately named
action that explains remote authority and already-open sessions remain until
revocation/re-pair or expiry. Neither action deletes saved dialogue, appearance
preferences or the ChatGPT account connection. A failed storage write after
redemption is reported as incomplete setup and requires a newly generated code.

## Verification

- Full mocked API suite: 107 passed, with one existing dependency deprecation
  warning. Runs in the existing test image with networking disabled and a fresh
  temporary auth directory; the real credential volume is never mounted.
- Extension wiring plus 82 behavior/cache/Settings regressions pass, including
  23 new Settings/launch tests. All extension JavaScript syntax, manifest JSON
  and `git diff --check` pass.
- BrowserOS neo used the real Options HTML/CSS/JS with a generated-data Chrome
  API shim: pairing enabled management, reload retained it, and status checks
  sent no inference. The model dropdown was exercised. Options, locked settings,
  model settings and catalog-error layouts had no horizontal overflow at
  280, 360 and 740 px. Light/dark previews use generated account/model data.
- This preview does not certify installed-extension Origin serialization,
  top-level POST/cookie handoff, Chrome storage lifecycle or live OAuth. Keep
  the PR Draft until real Chrome acceptance and security review. Existing
  Reader/cache manual acceptance does not cover this new flow.

| Remembered connection | Model settings / dark |
| --- | --- |
| ![Connection](assets/settings-connected.png) | ![Model settings](assets/settings-models-dark.png) |

[First-time pairing preview](assets/settings-onboarding.png).

## Actual Chrome acceptance

1. Update the gateway with `docker compose up --build -d api`, reload the unpacked
   extension, and open Options. Existing reader-only pairing should still work
   for translation and offer explicit re-pairing for management.
2. In your own terminal run `docker compose exec api python -m app.local_security
   pair`; enter the displayed code and explicitly grant management permission.
   Do not paste codes, credentials or OAuth callback URLs into bug reports.
3. Open **จัดการการเชื่อมต่อ**. Confirm a new local Settings tab opens authenticated
   without admin-key entry or URL credentials. Connect ChatGPT if needed, choose
   an available vision-capable model and save. Returning to Options refreshes
   its status automatically.
4. Restart the gateway and the extension worker, reopen Options and management.
   Pairing should persist; an expired browser session should reopen without a
   new code. This setup does not itself submit a translation.
5. Leave an authenticated Settings tab open, then revoke or re-pair. Its next
   account/model mutation must fail, and a previously minted ticket must not
   establish a session. Confirm saved translations and reading preferences stay.
6. Exercise wrong/expired codes, denied consent, gateway offline and local-only
   forgetting. Model-list errors should preserve the selected model.

Roll out or roll back extension and gateway together. A new pairing replaces the
single previously paired extension; reverting code does not restore an older
credential, so use a fresh pairing if needed. Do not expand origin permissions,
expose the gateway remotely or merge automatically.
