const API = "http://127.0.0.1:8000/api/v1/translate";
const SUPPORTED_IMAGE_HOSTS = new Set(["cdn.asurascans.com"]);

chrome.action.onClicked.addListener(async tab => {
  if (!tab.id || !/^https?:\/\//.test(tab.url || "")) return;
  try {
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["content.js"]});
  } catch (error) {
    console.warn("Cannot inject Manga Translator:", error);
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "MANGA_FETCH_TRANSLATE") return false;
  (async () => {
    if (!sender.tab?.id || !sender.tab?.url) throw new Error("Request must originate from a tab");
    let imageUrl;
    try {
      imageUrl = new URL(message.url);
    } catch {
      throw new Error("Invalid image URL");
    }
    const pageUrl = new URL(sender.tab.url);
    if (imageUrl.protocol !== "https:" && imageUrl.origin !== pageUrl.origin) {
      throw new Error("Insecure image origin not allowed");
    }
    if (imageUrl.origin !== pageUrl.origin && !SUPPORTED_IMAGE_HOSTS.has(imageUrl.hostname)) {
      throw new Error("Image CDN not permitted: " + imageUrl.hostname);
    }
    // Fetch in extension service worker, not from the webpage/content script.
    // Browser extension host_permissions enable cross-origin requests for this origin.
    let response;
    try {
      response = await fetch(imageUrl.href, {credentials: "omit", redirect: "error"});
    } catch {
      throw new Error("Unable to fetch image from CDN. Check Chrome extension host permissions and CDN access policy.");
    }
    if (!response.ok) throw new Error("Image server returned HTTP " + response.status);
    const contentType = response.headers.get("content-type")?.split(";")[0] || "";
    if (!["image/png","image/jpeg","image/webp"].includes(contentType)) {
      throw new Error("Unsupported image content-type: " + contentType);
    }
    const length = Number(response.headers.get("content-length") || 0);
    if (length > 8 * 1024 * 1024) throw new Error("Image exceeds 8MB limit");
    const blob = await response.blob();
    if (blob.size > 8 * 1024 * 1024) throw new Error("Image exceeds 8MB limit");
    const form = new FormData();
    form.append("file", blob, "panel.webp");
    let apiResponse;
    try {
      apiResponse = await fetch(API, {method: "POST", body: form});
    } catch {
      throw new Error("Local translation API is offline at 127.0.0.1:8000");
    }
    if (!apiResponse.ok) throw new Error("Translation API returned HTTP " + apiResponse.status);
    return apiResponse.json();
  })().then(data => sendResponse({ok: true, data}), error => sendResponse({ok: false, error: String(error)}));
  return true;
});
