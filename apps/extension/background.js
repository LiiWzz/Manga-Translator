const API = "http://127.0.0.1:8000/api/v1/translate-rendered";
const SUPPORTED_IMAGE_HOSTS = new Set(["cdn.asurascans.com"]);
const MAX_BYTES = 8 * 1024 * 1024;

chrome.action.onClicked.addListener(async tab => {
  if (!tab.id || !/^https?:\/\//.test(tab.url || "")) return;
  try {
    await chrome.scripting.executeScript({
      target: {tabId: tab.id},
      files: ["content.js"]
    });
  } catch (error) {
    console.warn("Manga Translator: cannot inject", error);
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "MANGA_RENDER_TRANSLATE") return false;
  (async () => {
    if (!sender.tab?.id || !sender.tab?.url || typeof message.url !== "string") {
      throw new Error("Invalid translation request");
    }
    const page = new URL(sender.tab.url);
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
    let response;
    try {
      response = await fetch(API, {method: "POST", body: form});
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
