# Image access and CORS troubleshooting

A browser can display a cross-origin `<img>` even when page JavaScript cannot read its bytes. Reader fetches image bytes in its extension service worker using explicit Chrome host access. It does not modify server headers or disable browser protections.

1. Reload the extension in `chrome://extensions` after updating, reopen Reader and refresh the source page.
2. Keep the local companion/gateway running and pair the extension in Options.
3. Click **แปลภาพที่เห็น**. If prompted, use **อนุญาตเว็บไซต์ …** to approve the source page's origin.
4. If an image comes from an unapproved origin, its card shows **อนุญาตรูปจาก …**. Review the displayed image domain and Chrome prompt. Approving retries that image; denying leaves it unsubmitted.
5. Scroll until the image has loaded, then scan again. Discovery covers up to three eligible visible `<img>` elements in the main document.

There is no longer a fixed CDN allowlist in Reader. The existing CDN permission stays in the manifest for compatibility; all additional origins use the already-declared optional permissions and require a specific user grant.

## Other page layouts

For canvas, CSS background images, `blob:`/`data:` images, shadow DOM or iframe readers, use **เลือกพื้นที่แปลจากหน้าจอ**. This captures the visible HTTP/HTTPS tab and displays a local preview. Select a region, review it, then explicitly submit that crop. If capture is unavailable, click the extension's toolbar icon on that tab to grant temporary `activeTab` access, and try again. Permanent page/CDN access does not replace the capture permission.

See [site compatibility](SITE_COMPATIBILITY.md) for screenshot limits and remaining Chrome acceptance checks.

## Server restrictions

Host permission does not guarantee access. Requests omit cookies and reject redirects. HTTP 401/403, anti-hotlink rules, paywalls, anti-bot protections and other server restrictions remain errors; Reader does not retry them with credentials or proxies. Use only content you have permission to access and translate. Do not use capture to circumvent access or copyright restrictions.

Direct fetching supports PNG, JPEG and WebP, up to 8 MiB, with a 15-second request timeout. Unsupported MIME types and oversized responses are rejected; streaming downloads stop once the byte limit is exceeded. Image decoding and vision have additional dimension/crop limits. No mode promises support for every site or whole-chapter translation.
