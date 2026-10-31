/* Non-destructive Side Panel: edits stay local and manga image pixels stay untouched. */
const status = document.getElementById("status");
const items = document.getElementById("items");
const scanButton = document.getElementById("scan");
const grantButton = document.getElementById("grant");
const cache = new Map();
const rendered = new Set();
let generation = 0;
let context = "";
let running = false;
let pendingPermission = null;

function show(message) { status.textContent = message; }
function element(tag, className, value) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (value != null) el.textContent = value;
  return el;
}

async function activeMangaTab() {
  // The Side Panel does not get a new activeTab grant from its own buttons.
  // The 'tabs' permission supplies metadata; host permission is requested separately.
  const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  if (!tab?.id) {
    throw new Error("ไม่พบแท็บที่กำลังใช้งาน กรุณาเลือกแท็บมังงะในหน้าต่าง Chrome");
  }
  if (!tab.url) {
    throw new Error("อ่าน URL แท็บไม่ได้: Reload ส่วนขยายและตรวจสิทธิ์ tabs ใน chrome://extensions");
  }
  if (!/^https?:\/\//.test(tab.url)) {
    throw new Error("แท็บปัจจุบันไม่ใช่เว็บ http/https: " + tab.url.slice(0, 70));
  }
  return tab;
}

function clearPendingPermission() {
  pendingPermission = null;
  grantButton.hidden = true;
}

function render(data) {
  data.regions.forEach((r, index) => {
    const card = element("section", "item");
    const label = element("small", "", "ภาพ " + (data.imageIndex + 1) + " · บทสนทนา " + (index + 1));
    const original = element("div", "source", r.source_text);
    const translated = element("div", "translation", r.translated_text);
    const controls = element("div", "tools");
    const edit = element("button", "", "แก้คำแปล");
    const locate = element("button", "", "ไปยังภาพ");
    edit.addEventListener("click", () => {
      if (card.querySelector("textarea")) return;
      const input = document.createElement("textarea");
      input.value = translated.textContent;
      const save = element("button", "", "บันทึก");
      save.addEventListener("click", () => {
        translated.textContent = input.value;
        input.remove();
        save.remove();
        data.regions[index].translated_text = translated.textContent;
      });
      card.append(input, save);
      input.focus();
    });
    locate.addEventListener("click", async () => {
      try {
        await chrome.tabs.sendMessage(data.tabId, {type: "MANGA_READER_LOCATE", index: data.imageIndex});
      } catch {
        show("ไม่พบภาพต้นฉบับ กรุณาเปิดแท็บมังงะเดิมแล้วลองอีกครั้ง");
      }
    });
    controls.append(edit, locate);
    card.append(label, original, translated, controls);
    items.append(card);
  });
}

async function scan() {
  if (running) return;
  running = true;
  const task = ++generation;
  scanButton.disabled = true;
  try {
    const tab = await activeMangaTab();
    const origin = new URL(tab.url).origin;
    const pattern = origin + "/*";
    if (!await chrome.permissions.contains({origins: [pattern]})) {
      pendingPermission = {tabId: tab.id, origin, pattern};
      grantButton.textContent = "อนุญาตเว็บไซต์ " + new URL(tab.url).hostname;
      grantButton.hidden = false;
      show("ต้องอนุญาตให้ Reader อ่านรูปจากเว็บไซต์นี้ก่อน (เฉพาะโดเมนนี้)");
      return;
    }
    clearPendingPermission();

    try {
      await chrome.scripting.executeScript({
        target: {tabId: tab.id},
        files: ["reader-content.js"]
      });
    } catch (error) {
      throw new Error("เข้าอ่านภาพบนแท็บนี้ไม่ได้: " + (error.message || String(error)));
    }
    const images = await chrome.tabs.sendMessage(tab.id, {type: "MANGA_READER_DISCOVER"});
    if (!Array.isArray(images) || !images.length) {
      throw new Error("ไม่พบรูปมังงะที่โหลดแล้วในหน้าจอ ลองเลื่อนหน้าให้รูปปรากฏและกดแปลอีกครั้ง");
    }
    let added = 0, errors = 0, empty = 0;
    for (let i = 0; i < images.length; i++) {
      if (task !== generation) break;
      const image = images[i];
      const key = tab.id + ":" + image.url;
      if (rendered.has(key)) continue;
      let data = cache.get(key);
      if (!data) {
        show("กำลัง OCR/แปล " + (i + 1) + "/" + images.length + " (" + origin + ")");
        const reply = await chrome.runtime.sendMessage({
          type: "MANGA_READER_TRANSLATE", url: image.url, tabId: tab.id,
          context: context.slice(-1500)
        });
        if (!reply?.ok) {
          errors++;
          show("ภาพ " + (i + 1) + " แปลไม่สำเร็จ: " + (reply?.error || "ไม่ทราบสาเหตุ"));
          continue;
        }
        data = reply.data;
        cache.set(key, data);
      }
      if (!Array.isArray(data.regions) || data.regions.length === 0) {
        empty++;
        continue;
      }
      data.imageIndex = image.index;
      data.tabId = tab.id;
      render(data);
      rendered.add(key);
      added += data.regions.length;
      context = (context + " " + data.regions.map(r =>
        r.source_text + " => " + r.translated_text).join(" ")).slice(-1500);
    }
    if (task === generation) {
      show("เพิ่ม " + added + " บทสนทนา · ภาพ OCR ไม่พบข้อความ " + empty +
           " · ล้มเหลว " + errors + " · เลื่อนหน้าเพื่อแปลภาพถัดไป");
    }
  } catch (error) {
    if (task === generation) show(error.message || String(error));
  } finally {
    running = false;
    scanButton.disabled = false;
  }
}

scanButton.addEventListener("click", scan);

// Chrome requires a direct user gesture for permission requests.
// Do NOT await chrome.tabs.query before calling permissions.request here.
grantButton.addEventListener("click", () => {
  const request = pendingPermission;
  if (!request) return;
  chrome.permissions.request({origins: [request.pattern]}).then(async allowed => {
    if (!allowed) {
      show("ยังไม่ได้อนุญาตเว็บไซต์นี้ จึงไม่สามารถ OCR รูปในหน้านี้ได้");
      return;
    }
    clearPendingPermission();
    await scan();
  }).catch(error => show("ขอสิทธิ์เข้าถึงเว็บไม่สำเร็จ: " + (error.message || error)));
});

document.getElementById("reset").addEventListener("click", () => {
  ++generation;
  cache.clear();
  rendered.clear();
  context = "";
  clearPendingPermission();
  items.replaceChildren();
  show("เริ่มใหม่แล้ว");
});
document.getElementById("settings").addEventListener("click", () => chrome.runtime.openOptionsPage());
