# Manga Translator v0.3 — Sign in with ChatGPT (OSS/local POC)

Chrome Extension for translating English manga dialogue into Thai through a **local FastAPI gateway**. v0.3 adds officially supported OpenAI Sign in with ChatGPT for eligible open-source/local apps, **without requiring an API key**.

**Status:** Draft PR / local prototype. Unit and CI checks cover mocked OAuth behavior. Live Reader inference has been exercised with a connected account, and the user accepted the latest translation fix. Full OAuth/browser and security acceptance remains incomplete; this is not a production-ready auth service.

## Development direction

The current Reader branch uses **Vision + Chrome Side Panel**. The reliability baseline has user-reported Chrome acceptance. The next feature branch adds [persistent local cache and corrections](docs/READER_CACHE.md), with automated checks passing and real Chrome acceptance pending. Translation quality, selected-region translation and controlled continuous reading follow in that order. **Optional overlay may be explored in v2**, subject to visual-quality and cost evaluation; it is not a committed feature and is distinct from the historical v0.2 prototype. See the [development roadmap](docs/POC_PLAN.md) and [current Reader workflow](docs/READER_V04.md). Earlier OAuth/overlay details are retained in [the v0.3 notes](docs/OAUTH_V03.md).

The current Settings branch adds [pair-once setup](docs/SETTINGS_PAIR_ONCE.md): a
temporary code issued from the local terminal authorizes the extension, which
remembers separate translation and Settings permissions. Normal use no longer
requires an admin key. Thai connection status and a model dropdown replace raw
JSON and model-slug copying. Real Chrome acceptance of this flow is pending.

The [Reader model picker](docs/READER_MODELS.md) builds on that Settings branch.
Reader automatically loads the connected account's available models and shows
the current model plus the number of choices in its header. Open it to select a
new model without leaving the panel. Selection saves immediately,
preserves displayed dialogue and unsaved edits, and applies to the next explicit
translation. Controls prevent changing models during this panel's queue or
starting translation during a model save. Real Chrome acceptance is pending.

## Requirements

For the Windows/macOS desktop companion (no Docker or Python needed on your
friend's machine), see [sharing with friends](docs/DESKTOP_DISTRIBUTION.md).
The native packaging workflow and local mock acceptance are separate from live
account/browser acceptance; unsigned test bundles are not a public release.

The source/Docker setup below remains available for development.

- Docker Desktop / Docker Engine
- Chrome desktop
- Eligible ChatGPT plan and explicit ChatGPT plan-sharing consent
- Authorized image hosting for manga pages

## Install and run

```sh
git fetch origin
git switch fix/settings-extension-get-origin
git pull origin fix/settings-extension-get-origin
```

Check `.env`, or create it with `cp .env.example .env`. Make sure it contains:

```dotenv
TRANSLATOR_PROVIDER=chatgpt_oauth
```

The API, Compose and `.env.example` default to `mock`: Reader shows clearly
marked generated demo text without calling OpenAI. Set `chatgpt_oauth` explicitly
for real image translation. Existing `.env` values remain authoritative.

```sh
docker compose up --build -d
curl http://127.0.0.1:8000/health
```

In Chrome, open `chrome://extensions` → Enable **Developer Mode** → **Load unpacked** → select `apps/extension`. If already installed, click **Reload**.

**Pair with this machine (required once for the new Settings flow):**

```sh
docker compose exec api python -m app.local_security pair
```

Open Extension Options, paste the temporary code, explicitly allow translation
and local Settings management, and click **จับคู่และจำเครื่องนี้**. The code is
single-use and expires after ten minutes. No permanent admin key needs to be
created or saved. Do not share the code or include it in logs or bug reports.
Completing a new pairing replaces the previous extension. Existing ChatGPT
connection and saved translations are retained.

Click **จัดการการเชื่อมต่อ** in Extension Options. This opens an authenticated
local Settings tab without putting credentials in its URL. Opening `/settings`
directly remains locked unless this browser already has a valid Settings session.

1. Click **เชื่อมต่อ ChatGPT**. This opens the official OpenAI authorization page.
2. Complete registration and review the requested ChatGPT plan-use consent.
3. Return to local Settings and confirm the account and plan permission are connected.
4. Select a model from the account-specific dropdown and click **บันทึกโมเดล**.
   Choose a vision-capable model; the catalog alone does not establish image support.
5. Return to your authorized manga-reader tab, open the extension Side Panel and
   click **แปลภาพที่เห็น**. It attempts up to three eligible images.

Later visits to Extension Options show the connection status and next action.
Opening management settings reuses the remembered extension permission; its
browser session lasts at most 30 minutes. If it expires, reopen from Options.
Re-pairing or revoking the extension invalidates its management sessions. Legacy
reader-only pairing continues to translate but needs explicit new pairing for
Settings authority. Old admin-key unlock remains under recovery. See
[pair-once behavior and acceptance](docs/SETTINGS_PAIR_ONCE.md) and the
[security notes](docs/SECURITY_V031.md).

If sign-in fails, inspect the localhost Settings error. The callback and model discovery have not been verified with a live account in this POC; do not expose secrets in support reports.

Connection/model reliability checks now prevent a late token refresh from
restoring an older account or model. Browser Settings model forms carry an
account-selection version and recheck management authority immediately before
saving. Reload a Settings page opened before this update before saving a model.
Terminal refresh failures offer reconnection with the saved registration;
temporary provider/network failures preserve credentials. The API returns safe
error categories and the model associated with a validated Reader result.
Installed Chrome/OAuth acceptance of this follow-up remains pending.

Options and Reader now distinguish expired connections, plan permission,
usage limits, unsupported capabilities and temporary provider failures. Reader
stops unsent queue items for account/usage/model-wide failures and offers a
Settings or Usage action. Ordinary image errors still have explicit retries.
The extension displays app-owned recovery text rather than raw provider errors.

The Reader picker is labeled **แปลครั้งถัดไป**. Each result retains its source
model through model changes, edits and cache reloads. Older cached results with
no model metadata display an unknown-model label; they are never assigned the
currently selected model. Mock results are visibly marked as generated demo text.

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
