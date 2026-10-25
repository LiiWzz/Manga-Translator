# CORS troubleshooting — asurascans image CDN

Symptom:
`Access to fetch at https://cdn.asurascans.com/... from origin https://asurascans.com has been blocked by CORS policy`

Cause: calling `fetch(imageUrl)` in website context or content script does not bypass the image CDN's cross-origin policy. The browser may display an image as an `<img>` while JavaScript cannot read its bytes.

## Fix in this POC

The extension's **background service worker** fetches CDN image bytes using its explicit `https://cdn.asurascans.com/*` host permission, then sends the image to the local FastAPI OCR backend. The content script sends only the URL and renders the response. We do not change the origin server's CORS headers and do not turn off browser security.

1. Check out `feat/engineering-poc-v0.1`.
2. Load unpacked from `apps/extension` (containing `manifest.json`).
3. Click **Reload** on the extension card after pulling the latest source, then refresh the manga webpage.
4. Ensure `http://127.0.0.1:8000/health` responds.
5. Open the Extension's **Service worker** inspector on `chrome://extensions` for fetch and API errors.

**Important:** If Console refers to `inject.js`, you are running a different/older extension build. This repo's standalone version consists of `background.js` and `content.js`.

## Restrictions

Cross-origin host permission is not a guarantee that an image is accessible. The CDN can reject unauthenticated requests (HTTP 401/403), deny hotlinking, or require other access conditions. In these situations respect the site's restrictions; do not circumvent them. Ask for site authorization or test on an allowed image source.

The on-click POC works on three visible images and is not a complete site adapter. Do not distribute translated copyrighted image collections without permission.
