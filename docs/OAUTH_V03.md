# ChatGPT OAuth v0.3 — Local OSS POC

## Goals
- Use the supported **Sign in with ChatGPT open-source/local app** flow, without scraping ChatGPT cookies or using an OpenAI API key.
- Register through `dynamic_agent_client`; retain the issued `oaiapp_...` client ID. Persist a stable host ID.
- Validate OAuth state, PKCE S256 and a nonce-checked OpenAI-signed ID token. Check granted `chatgpt.tokens.use.direct` scope.
- Keep access, refresh and ID tokens in owner-only backend files on a persistent Docker volume; rotate refresh tokens.
- Stream a Responses API request using `store:false`, `stream:true`; accept success **only** after `response.completed`.
- Choose models from the authenticated account's `GET /v1/models` list; do not hard-code entitlement.
- Never disclose tokens to the extension, use only local loopback HTTP (host-bound port).
- CSRF-protect local settings actions; avoid OAuth tokens in URL/logs.

## Installation
1. Checkout `feat/chatgpt-oauth-provider-v0.3`.
2. Ensure `.env` sets `TRANSLATOR_PROVIDER=chatgpt_oauth`. An old `.env` using mock/openai overrides Compose defaults.
3. Run `docker compose up -d --build`.
4. Open `http://127.0.0.1:8000/settings` in Chrome or navigate via extension Options.
5. Click **Continue with ChatGPT**, approve access and plan usage, then return to settings.
6. Open `/auth/models`, select an available `slug` using the local Settings form.
7. Reload the extension from `apps/extension`, then click its icon on an authorized manga page.

## Security review / boundaries
- Prototype is **single-account**, not a multi-user or remote hosted auth service. It is for one local developer workstation only.
- Local URLs may be reached by other local processes; loopback binding is **not an authentication boundary**. Do not publish port 8000 or forward it on LAN. Browser-accessible image translation endpoint is currently unauthenticated (pre-existing security debt).
- File permissions 0700 directory / 0600 token records mitigate accidental disclosure; they are not OS-keychain encryption and do not protect a compromised OS account.
- Pending OAuth state lives in one Python process; restarting during OAuth requires starting a new sign-in.
- Cookie + CSRF protects settings POSTs in ordinary browser scenarios. The callback itself validates state and nonce; callbacks from the authorization server are expected to be cross-site.
- Code must be reviewed for actual OpenAI payloads and callback behavior. The implementation has simulated tests, **not proof** of a successful real-account OAuth exchange.
- Endpoint support may vary during OSS preview. Do not infer entitlement from successful basic login.
- Logout clears tokens locally and requests remote revocation; if remote revocation is unconfirmed, disconnect under ChatGPT Settings.
- Python and Docker log settings must not emit auth codes, URLs containing credentials, or tokens.
- Obtain authorization for accessed manga pages. No bypassing website access restrictions.

## Verification gates
- [ ] Local / CI tests
- [ ] Review official SIWC authorization, callback and token schemas against live implementation
- [ ] Test successful sign-in with real eligible account and explicit user consent
- [ ] Verify granted scopes, token refresh, denied consent and logout
- [ ] Verify model picker + response.completed with a real call
- [ ] Threat model cross-origin and local process callers
- [ ] Browser E2E and original manga image integrity
- [ ] Human approval before any merge

References:
https://developers.openai.com/siwc/token-sharing-open-source/sign-in
https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
