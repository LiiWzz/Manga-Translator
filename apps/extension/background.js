const API = "http://127.0.0.1:8000/api/v1/translate";
chrome.action.onClicked.addListener(async tab => {
  if (!tab.id || !/^https?:\/\//.test(tab.url || "")) return;
  try {
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["content.js"]});
  } catch (error) {
    console.warn("Cannot inject Manga Translator into this tab:", error);
  }
});
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "MANGA_FETCH_TRANSLATE") return false;
  (async () => {
    const url = message.url;
    if (!/^https?:\/\//.test(url) || !sender.tab?.id) throw new Error("Invalid request");
    // activeTab grants temporary access to the active tab's origin; other CDN origins
    // may still be blocked unless separately approved by the user.
    const imageResponse = await fetch(url, {credentials: "omit"});
    if (!imageResponse.ok) throw new Error("Image fetch failed: " + imageResponse.status);
    const blob = await imageResponse.blob();
    if (blob.size > 8 * 1024 * 1024) throw new Error("Image exceeds size limit");
    const form = new FormData();
    form.append("file", blob, "panel.png");
    const apiResponse = await fetch(API, {method: "POST", body: form});
    if (!apiResponse.ok) throw new Error("Translate API returned " + apiResponse.status);
    return apiResponse.json();
  })().then(data => sendResponse({ok: true, data}), error => sendResponse({ok: false, error: String(error)}));
  return true;
});
