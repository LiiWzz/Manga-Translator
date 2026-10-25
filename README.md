# Manga Translator v0.3 — Sign in with ChatGPT (OSS/local POC)

Chrome Extension for translating English manga dialogue into Thai through a **local FastAPI gateway**. v0.3 adds officially supported OpenAI Sign in with ChatGPT for eligible open-source/local apps, **without requiring an API key**.

**Status:** Draft PR / prototype. Unit and CI checks cover mocked OAuth behavior. A real ChatGPT login and a live Responses API call have **not yet been validated**. Do not distribute as a production-ready auth service.

## Requirements

- Docker Desktop / Docker Engine
- Chrome desktop
- Eligible ChatGPT plan and explicit ChatGPT plan-sharing consent
- Authorized image hosting for manga pages

## Install and run

```sh
git fetch origin
git switch feat/chatgpt-oauth-provider-v0.3
git pull origin feat/chatgpt-oauth-provider-v0.3
```

Check `.env`, or create it with `cp .env.example .env`. Make sure it contains:

```dotenv
TRANSLATOR_PROVIDER=chatgpt_oauth
```

Old `.env` files specifying `mock` or `openai` override the new default.

```sh
docker compose up --build -d
curl http://127.0.0.1:8000/health
```

In Chrome, open `chrome://extensions` → Enable **Developer Mode** → **Load unpacked** → select `apps/extension`. If already installed, click **Reload**.

In Extension Details → **Extension options**, click **Open ChatGPT connection settings** (or open `http://127.0.0.1:8000/settings` directly).

1. Click **Continue with ChatGPT**. This opens the official OpenAI authorization page.
2. Complete registration and review the requested ChatGPT plan-use consent.
3. Return to local Settings and confirm the account has `plan_usage_enabled`.
4. Open `http://127.0.0.1:8000/auth/models` while the local Settings session is active.
5. Copy an available `slug` from the account-specific catalog into the Settings model input and click Save Model.
6. Refresh your authorized manga-reader tab and click the extension toolbar icon. It attempts up to three eligible images.

If sign-in fails, inspect the localhost Settings error. The callback and model discovery have not been verified with a live account in this POC; do not expose secrets in support reports.

## Architecture

- Chrome MV3 extension: image detection, limited CDN loading, safe overlay.
- FastAPI: OCR (Tesseract), translation provider adapter, transparent bubble renderer.
- OAuth: state / nonce / PKCE, issued client ID, JWKS ID-token verification, granted-scope gate, refresh rotation.
- File storage on an owner-only Docker volume. Tokens remain server-side and never go into the Chrome extension.
- Model selection from the connected account's `GET /v1/models` catalog.
- Responses API stream with `store: false`, `stream: true`; waits for `response.completed`.

## Tests

GitHub Actions checks backend and extension syntax. To run locally:

```sh
cd apps/api
pip install -e '.[test]'
pytest -q
```

Local tests need a Thai TrueType font (`THAI_FONT_PATH`) or a system package such as `fonts-noto-core`.

## Important limitations

- **Single local user only**. Do not port-forward or expose port 8000.
- Plaintext OAuth credentials in owner-only storage (0600/0700), not an encrypted OS keychain.
- In-memory OAuth transaction only, requiring one backend worker. Restarting during authorization invalidates the attempt.
- The pre-existing translate endpoint is not protected from all local callers; treat as security debt before distribution.
- OAuth sign-in does not guarantee `chatgpt.tokens.use.direct` permission or unlimited model use.
- OCR is line-grouping heuristic; bubble renderer skips textured/unsafe regions, not full inpainting.
- Respect manga licensing and website permissions.

See [OAuth implementation and security review](docs/OAUTH_V03.md), [Bubble rendering acceptance](docs/V02_ACCEPTANCE.md), and [CDN troubleshooting](docs/CORS_TROUBLESHOOTING.md).

## Source documents

- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
