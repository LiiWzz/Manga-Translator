const API = "http://127.0.0.1:8000/api/v1/translate-rendered";
const SUPPORTED_IMAGE_HOSTS = new Set(["cdn.asurascans.com"]);
const MAX_BYTES = 8 * 1024 * 1024;

// Let Chrome own action-icon opening. sidePanel.open() requires a user gesture
// and fails if an await (such as scripting.executeScript) precedes it.
// Reapply on service-worker startup; Chrome persists the behavior across restarts.
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true})
  .catch(error => console.error("Manga Reader: cannot enable toolbar side panel", error));

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "MANGA_RENDER_TRANSLATE" && message.type !== "MANGA_READER_TRANSLATE") return false;
  (async () => {
    const {mangaCapability, mangaDebug} = await chrome.storage.local.get(["mangaCapability", "mangaDebug"]);
    if (!mangaCapability) throw new Error("Pair extension in Options first");
    const reader = message.type === "MANGA_READER_TRANSLATE";
    if (typeof message.url !== "string") throw new Error("Invalid image URL");
    let tab = sender.tab;
    if (reader) {
      if (sender.id !== chrome.runtime.id || !Number.isInteger(message.tabId)) {
        throw new Error("Invalid reader source");
      }
      const [candidate, active] = await Promise.all([
        chrome.tabs.get(message.tabId), chrome.tabs.query({active:true,currentWindow:true})
      ]);
      if (!active.some(t => t.id === candidate.id)) throw new Error("Source tab is not active");
      tab = candidate;
    }
    if (!tab?.id || !tab?.url) throw new Error("Invalid translation source");
    const page = new URL(tab.url);
    const image = new URL(message.url);
    if (image.protocol !== "https:" && image.origin !== page.origin) {
      throw new Error("Insecure image URL");
    }
    if (image.origin !== page.origin && !SUPPORTED_IMAGE_HOSTS.has(image.hostname)) {
      throw new Error("CDN access is not configured for " + image.hostname);
    }
    // Browser extension service worker fetches the image with explicit host permission.
    // Never attempt to bypass the website's authentication or server-side access policy.
    let imageResponse;
    try {
      imageResponse = await fetch(image.href, {credentials: "omit", redirect: "error"});
    } catch {
      throw new Error("Image request blocked. Check CDN permissions or access policy.");
    }
    if (!imageResponse.ok) throw new Error("Image HTTP " + imageResponse.status);
    const mime = imageResponse.headers.get("content-type")?.split(";")[0] || "";
    if (!["image/png", "image/jpeg", "image/webp"].includes(mime)) {
      throw new Error("Unsupported image MIME: " + mime);
    }
    if (Number(imageResponse.headers.get("content-length") || 0) > MAX_BYTES) {
      throw new Error("Image exceeds 8 MB limit");
    }
    const blob = await imageResponse.blob();
    if (blob.size > MAX_BYTES) throw new Error("Image exceeds 8 MB limit");
    const form = new FormData();
    form.append("file", blob, "panel.webp");
    if (reader) form.append("context", String(message.context || "").slice(0,1500));
    let response;
    try {
      response = await fetch(reader ? "http://127.0.0.1:8000/api/v1/reader/translate" : API + (mangaDebug ? "?debug=true" : ""), {method: "POST", body: form, headers: {Authorization: "Bearer " + mangaCapability}});
    } catch {
      throw new Error("OCR API is offline at http://127.0.0.1:8000");
    }
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new Error("Translation API HTTP " + response.status + ": " + body.slice(0, 180));
    }
    return response.json();
  })().then(data => sendResponse({ok: true, data}), error => sendResponse({ok: false, error: String(error)}));
  return true;
});
