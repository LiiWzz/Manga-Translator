# v0.3.1 P0 Security ADR — Draft / Local-only

## Scope / assumptions
One operator, one FastAPI worker, Docker host port `127.0.0.1:8000`. Local processes and browser origins are untrusted. A compromised OS user or a privileged local process that reads Docker volumes / Chrome storage is outside this POC's protection. Do **not** expose the API over LAN or proxy.

## Admin bootstrap
`docker compose exec api python -m app.local_security init` prints a 256-bit key once to the terminal. It is hashed using scrypt in a 0600 backend-owned file. On first visit `/settings` shows a locked screen. Enter the key in the HTML form to unlock the CSRF-protected session (HttpOnly, SameSite=Lax). Only unlocked sessions can begin/reconnect OAuth, list models, change model, disconnect, issue or revoke extension pairing. Never paste the admin key into URLs or logs.

If the key is lost, run `docker compose exec api python -m app.local_security reset-admin`. This resets pairing and issues a new key; restart the API to invalidate in-memory unlocked sessions. Resetting the admin key does not revoke OpenAI tokens.

## Extension pairing
An unlocked operator requests a one-use pairing code from `/auth/pair`, then enters that code in extension Options within ten minutes. Redeeming via `/api/v1/pair/redeem` atomically issues a random bearer capability; the server stores only its SHA-256 digest. Extension stores its *local-only* capability in `chrome.storage.local`, never an OpenAI token. Re-pairing rotates the old capability. The bearer is required for both translation APIs and provider status. The code and bearer are sensitive: never log them. Revoke through the authenticated Settings UI.

## OAuth
Pending attempts are keyed by cryptographically random state, bounded to 32 outstanding attempts with ten-minute TTL, optionally tied to unlocked Settings session ID, and atomically consumed only after state and session validation. Unknown or mismatched state cannot cancel a different attempt. One FastAPI worker is required (pending OAuth and settings sessions remain in memory); restart invalidates pending sign-ins.

## Threats and residual work
Host checks reject host-header based rebinding; Origin / Fetch Metadata checks mitigate browser CSRF and cross-origin requests, but are not client authentication. A local non-browser client may spoof them, which is why pairing/admin secrets are mandatory. SameSite=Lax permits the IdP top-level GET callback. CSP allows trusted OAuth redirect form behavior. Existing OCR worker admission/performance controls, OAuth registration persistence/refresh recovery, and real browser OAuth E2E remain **unresolved P1**; do not merge this Draft PR.

## Security gates
Automated tests cover access denial before decode/OCR, invalid Host/Origin, admin CSRF, single-use/expiry/revocation of pairing codes, OAuth concurrent attempts / session mismatch / replay / bounded state store. CI passing alone does not validate the full real-account OAuth/browser flow.
