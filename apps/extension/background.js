const API = "http://127.0.0.1:8000/api/v1/translate-rendered";
const SUPPORTED_IMAGE_HOSTS = new Set(["cdn.asurascans.com"]);
const MAX_BYTES = 8 * 1024 * 1024;
importScripts("reader-cache.js");
const readerCache = new ReaderCache(chrome.storage.local);
// Content scripts use messages only; neither cached dialogue nor pairing data
// needs to be exposed through storage APIs in the page's content-script context.
const storageReady = chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
storageReady.catch(() => console.error("Reader local storage could not be restricted"));

async function digest(value) {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map(byte => byte.toString(16).padStart(2, "0")).join("");
}
function readerPage(sender) {
  return sender.id === chrome.runtime.id &&
    sender.url === "chrome-extension://" + chrome.runtime.id + "/reader-panel.html";
}

// Let Chrome own action-icon opening. sidePanel.open() requires a user gesture
// and fails if an await (such as scripting.executeScript) precedes it.
// Reapply on service-worker startup; Chrome persists the behavior across restarts.
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true})
  .catch(error => console.error("Manga Reader: cannot enable toolbar side panel", error));

async function readerSource(message, sender) {
  if (sender.id !== chrome.runtime.id || !Number.isInteger(message.tabId) || typeof message.pageUrl !== "string") {
    throw new Error("Invalid reader source");
  }
  const [candidate, active] = await Promise.all([
    chrome.tabs.get(message.tabId), chrome.tabs.query({active:true,currentWindow:true})
  ]);
  if (!active.some(t => t.id === candidate.id)) throw new Error("Source tab is not active");
  if (candidate.url !== message.pageUrl || candidate.status === "loading") {
    throw new Error("Source page changed; scan the current page again");
  }
  return candidate;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "MANGA_READER_SAVE_EDIT" || message.type === "MANGA_READER_CLEAR_CACHE") {
    if (!readerPage(sender)) {
      sendResponse({ok: false, error: "Invalid Reader page"});
      return false;
    }
    const operation = storageReady.then(() => message.type === "MANGA_READER_CLEAR_CACHE" ? readerCache.clear()
      : readerCache.edit(message.key, message.index, message.text, message.epoch));
    operation.then(() => sendResponse({ok: true}), () => sendResponse({ok: false,
      error: "บันทึกหรือลบข้อมูลไม่สำเร็จ พื้นที่อาจเต็มหรือคำแปลหมดอายุ กรุณาลองอีกครั้ง"}));
    return true;
  }
  if (message.type !== "MANGA_RENDER_TRANSLATE" && message.type !== "MANGA_READER_TRANSLATE") return false;
  (async () => {
    await storageReady;
    const {mangaCapability, mangaDebug} = await chrome.storage.local.get(["mangaCapability", "mangaDebug"]);
    if (!mangaCapability) throw new Error("Pair extension in Options first");
    const reader = message.type === "MANGA_READER_TRANSLATE";
    if (reader && !readerPage(sender)) throw new Error("Invalid Reader page");
    let epoch = null, cacheWarning = "";
    if (reader) {
      try { epoch = await readerCache.begin(); }
      catch { cacheWarning = "แปลได้ แต่เปิดข้อมูลที่บันทึกไว้ไม่ได้"; }
    }
    if (typeof message.url !== "string") throw new Error("Invalid image URL");
    let tab = sender.tab;
    if (reader) tab = await readerSource(message, sender);
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
      imageResponse = await fetch(image.href, {credentials: "omit", redirect: "error", cache: "no-store"});
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
    let cacheKey, fingerprint;
    if (reader) {
      await readerSource(message, sender);
      const response = await fetch("http://127.0.0.1:8000/api/v1/reader/profile", {
        headers: {Authorization: "Bearer " + mangaCapability}, cache: "no-store"
      });
      if (!response.ok) throw new Error("Reader settings HTTP " + response.status);
      fingerprint = (await response.json()).fingerprint;
      if (!/^[a-f0-9]{64}$/.test(fingerprint)) throw new Error("Update the local API before using Reader cache");
      cacheKey = await digest(JSON.stringify([
        "reader-cache-1", message.pageUrl, await digest(await blob.arrayBuffer()),
        fingerprint, String(message.context || "").slice(0, 1500)
      ]));
      let saved;
      if (epoch) {
        try { saved = await readerCache.get(cacheKey, epoch); }
        catch { cacheWarning = "อ่านข้อมูลที่บันทึกไว้ไม่ได้ จะลองแปลภาพใหม่"; }
      }
      await readerSource(message, sender);
      if (epoch && await readerCache.begin() !== epoch) throw new Error("Saved Reader data was cleared; scan again");
      if (saved) return {...saved, cache_key: cacheKey, cache_epoch: epoch, cache_hit: true};
    }
    const form = new FormData();
    form.append("file", blob, "panel.webp");
    if (reader) form.append("context", String(message.context || "").slice(0,1500));
    if (reader) form.append("profile", fingerprint);
    // Fetching the image can outlive navigation. Do not submit old chapter context.
    if (reader) await readerSource(message, sender);
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
    const data = await response.json();
    if (!reader) return data;
    if (data.profile !== fingerprint) throw new Error("Reader settings changed; scan again");
    await readerSource(message, sender);
    let saved = false, stored;
    if (epoch) {
      try {
        saved = await readerCache.put(cacheKey, data, epoch);
        if (saved) stored = await readerCache.get(cacheKey, epoch);
        saved = Boolean(stored);
      }
      catch { cacheWarning = "แปลแล้ว แต่บันทึกถาวรไม่สำเร็จ กรุณาตรวจพื้นที่จัดเก็บ"; }
    }
    return {...(stored || ReaderCache.data(data)), cache_key: saved ? cacheKey : null,
      cache_epoch: saved ? epoch : null,
      cache_hit: false, cache_warning: saved ? "" : cacheWarning || "แปลแล้ว แต่ไม่ได้บันทึกถาวร"};
  })().then(data => sendResponse({ok: true, data}), error => sendResponse({ok: false, error: String(error)}));
  return true;
});
