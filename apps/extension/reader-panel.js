/* Non-destructive Reader with bounded local persistence owned by the worker. */
const status = document.getElementById("status");
const items = document.getElementById("items");
const scanButton = document.getElementById("scan");
const grantButton = document.getElementById("grant");
const clearButton = document.getElementById("clear-cache");
const imagesByUrl = new Map();
let generation = 0;
let source = null;
let activeRun = null;
let pendingPermission = null;
let clearing = false;

function show(message) { status.textContent = message; }
function element(tag, className, value) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (value != null) el.textContent = value;
  return el;
}

async function activeMangaTab() {
  // A Side Panel click does not grant activeTab; request per-site access separately.
  const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  if (!tab?.id) throw new Error("ไม่พบแท็บที่กำลังใช้งาน กรุณาเลือกแท็บมังงะในหน้าต่าง Chrome");
  if (!tab.url) throw new Error("อ่าน URL แท็บไม่ได้: Reload ส่วนขยายและตรวจสิทธิ์ tabs ใน chrome://extensions");
  if (!/^https?:\/\//.test(tab.url)) throw new Error("แท็บปัจจุบันไม่ใช่เว็บ http/https: " + tab.url.slice(0, 70));
  return tab;
}

function sameSource(a, b) { return a?.id === b?.id && a?.url === b?.url; }
function clearPendingPermission() {
  pendingPermission = null;
  grantButton.hidden = true;
}
function reset(message) {
  ++generation;
  activeRun = null;
  source = null;
  imagesByUrl.clear();
  clearPendingPermission();
  items.replaceChildren();
  scanButton.disabled = clearing;
  show(message);
}
function current(run) { return activeRun === run && run.generation === generation; }
async function verifySource(run) {
  if (!current(run)) return false;
  let tab;
  try {
    tab = await activeMangaTab();
  } catch {
    if (current(run)) reset("หน้าต้นทางไม่พร้อมใช้งาน กรุณาเปิดหน้ามังงะแล้วลองอีกครั้ง");
    return false;
  }
  if (!current(run)) return false;
  if (!sameSource(source, tab)) {
    reset("เปลี่ยนแท็บหรือหน้าแล้ว กดแปลภาพที่เห็นเพื่อเริ่มบริบทใหม่");
    return false;
  }
  return true;
}

function renderDialogue(record, r, index) {
  const card = element("section", "item");
  const label = element("small", "", "บทสนทนา " + (index + 1));
  const original = element("div", "source", r.source_text);
  const translated = element("div", "translation", r.translated_text);
  const controls = element("div", "tools");
  const edit = element("button", "", "แก้คำแปล");
  edit.addEventListener("click", () => {
    if (activeRun) { show("รอแปลภาพในคิวให้เสร็จก่อนแก้คำแปล"); return; }
    if (card.querySelector("textarea")) return;
    const input = document.createElement("textarea");
    input.value = translated.textContent;
    const save = element("button", "", "บันทึก");
    const cancel = element("button", "", "ยกเลิก");
    cancel.addEventListener("click", () => { input.remove(); save.remove(); cancel.remove(); });
    save.addEventListener("click", async () => {
      const epoch = generation, key = record.cacheKey, text = input.value;
      if (!key || !text.trim() || text.length > 1000) {
        show("ยังบันทึกไม่ได้: ต้องมีคำแปลที่บันทึกไว้ และข้อความไม่เกิน 1000 ตัวอักษร");
        return;
      }
      save.disabled = true;
      cancel.disabled = true;
      try {
        const reply = await chrome.runtime.sendMessage({type: "MANGA_READER_SAVE_EDIT", key, index, text, epoch: record.cacheEpoch});
        if (epoch !== generation || imagesByUrl.get(record.url) !== record || record.cacheKey !== key) return;
        if (!reply?.ok) throw new Error(reply?.error || "บันทึกคำแก้ไขไม่สำเร็จ กรุณาลองอีกครั้ง");
        translated.textContent = text;
        r.translated_text = text;
        input.remove();
        save.remove();
        cancel.remove();
        show("บันทึกคำแก้ไขในเครื่องแล้ว");
      } catch (error) {
        if (epoch === generation) show(error.message || String(error));
      } finally { save.disabled = false; cancel.disabled = false; }
    });
    card.append(input, save, cancel);
    input.focus();
  });
  controls.append(edit);
  card.append(label, original, translated, controls);
  record.card.append(card);
}

function renderImage(record) {
  record.card.replaceChildren(element("small", "", "ภาพ " + (record.index + 1)));
  if (record.cacheHit) record.card.append(element("small", "", " · ใช้คำแปลที่บันทึกไว้"));
  if (record.notice) record.card.append(element("div", "image-status", record.notice));
  if (record.state === "success") {
    record.regions.forEach((r, index) => renderDialogue(record, r, index));
    const locate = element("button", "", "ไปยังภาพ");
    locate.addEventListener("click", async () => {
      const epoch = generation;
      try {
        const tab = await activeMangaTab();
        if (epoch !== generation || !sameSource(source, tab)) return;
        const found = await chrome.tabs.sendMessage(tab.id, {
          type: "MANGA_READER_LOCATE", url: record.url, pageUrl: tab.url
        });
        if (!found && epoch === generation) show("ไม่พบภาพต้นฉบับในหน้านี้แล้ว");
      } catch {
        if (epoch === generation) show("ไม่พบภาพต้นฉบับ กรุณาเปิดแท็บมังงะเดิมแล้วลองอีกครั้ง");
      }
    });
    record.card.append(locate);
  } else {
    const messages = {queued: "รอแปล", loading: "กำลังแปล", empty: "ไม่พบบทสนทนาที่อ่านได้", error: "แปลไม่สำเร็จ: " + record.error};
    record.card.append(element("div", "image-status", messages[record.state]));
    if (record.state === "error") {
      const retry = element("button", "", "ลองใหม่");
      retry.disabled = Boolean(activeRun);
      retry.addEventListener("click", () => scan(record));
      record.card.append(retry);
    }
  }
}
function updateRetryButtons() {
  for (const record of imagesByUrl.values()) if (record.state === "error") renderImage(record);
}
function previousContext(record) {
  // Do not feed later images back into a retry of an earlier image.
  return [...imagesByUrl.values()].filter(r => r.state === "success" && r.index < record.index)
    .sort((a, b) => a.index - b.index)
    .flatMap(r => r.regions.map(row => row.source_text + " => " + row.translated_text))
    .join(" ").slice(-1500);
}
function showSummary() {
  const records = [...imagesByUrl.values()];
  const count = state => records.filter(r => r.state === state).length;
  show("แปลแล้ว " + count("success") + " ภาพ · ไม่พบบทสนทนา " + count("empty") +
    " · ล้มเหลว " + count("error") + " · เลื่อนหน้าเพื่อแปลภาพถัดไป");
}

async function translateRecord(run, record) {
  if (!await verifySource(run) || !current(run)) return;
  record.state = "loading";
  record.error = "";
  renderImage(record);
  show("กำลังแปลภาพ " + (record.index + 1));
  let reply;
  try {
    reply = await chrome.runtime.sendMessage({
      type: "MANGA_READER_TRANSLATE", url: record.url, tabId: source.id,
      pageUrl: source.url, context: previousContext(record)
    });
  } catch (error) {
    reply = {ok: false, error: error.message || String(error)};
  }
  if (!await verifySource(run) || !current(run)) return;
  const regions = reply?.data?.regions;
  if (!reply?.ok || !Array.isArray(regions) || regions.some(r =>
    !r || typeof r.source_text !== "string" || typeof r.translated_text !== "string")) {
    record.state = "error";
    record.error = reply?.error || "ข้อมูลคำแปลไม่ถูกต้อง กรุณาลองใหม่";
  } else {
    record.regions = regions;
    record.state = regions.length ? "success" : "empty";
    record.cacheKey = reply.data.cache_key;
    record.cacheEpoch = reply.data.cache_epoch;
    record.cacheHit = reply.data.cache_hit;
    record.notice = reply.data.cache_warning || "";
  }
  renderImage(record);
}

async function scan(retryRecord = null) {
  if (activeRun || clearing) return;
  if (items.querySelector("textarea")) { show("บันทึกหรือยกเลิกคำแก้ไขก่อนแปลภาพถัดไป"); return; }
  // Capture the generation before the first await, including tab/permission setup.
  const run = {generation};
  activeRun = run;
  scanButton.disabled = true;
  updateRetryButtons();
  try {
    const tab = await activeMangaTab();
    if (!current(run)) return;
    if (!sameSource(source, tab)) {
      reset("เริ่มบริบทสำหรับหน้านี้");
      source = tab;
      run.generation = generation;
      activeRun = run;
      scanButton.disabled = true;
      // An old retry must never be applied to another tab or chapter.
      if (retryRecord) return;
    }
    const origin = new URL(tab.url).origin;
    const pattern = origin + "/*";
    const allowed = await chrome.permissions.contains({origins: [pattern]});
    if (!await verifySource(run) || !current(run)) return;
    if (!allowed) {
      pendingPermission = {tabId: tab.id, pageUrl: tab.url, pattern, generation};
      grantButton.textContent = "อนุญาตเว็บไซต์ " + new URL(tab.url).hostname;
      grantButton.hidden = false;
      show("ต้องอนุญาตให้ Reader อ่านรูปจากเว็บไซต์นี้ก่อน (เฉพาะโดเมนนี้)");
      return;
    }
    clearPendingPermission();
    let queue;
    if (retryRecord) {
      if (imagesByUrl.get(retryRecord.url) !== retryRecord || retryRecord.state !== "error") return;
      queue = [retryRecord];
    } else {
      await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["reader-content.js"]});
      if (!await verifySource(run) || !current(run)) return;
      const images = await chrome.tabs.sendMessage(tab.id, {type: "MANGA_READER_DISCOVER", pageUrl: tab.url});
      if (!await verifySource(run) || !current(run)) return;
      if (!Array.isArray(images) || !images.length) {
        throw new Error("ไม่พบรูปมังงะที่โหลดแล้วในหน้าจอ ลองเลื่อนหน้าให้รูปปรากฏและกดแปลอีกครั้ง");
      }
      queue = [];
      for (const image of images.slice(0, 3)) {
        const existing = imagesByUrl.get(image.url);
        if (existing) {
          if (existing.state !== "error" && !queue.includes(existing)) {
            existing.index = image.index;
            queue.push(existing); // Worker revalidates bytes/profile/context before reuse.
          }
          continue;
        }
        const record = {...image, state: "queued", regions: [], error: "", card: element("section", "image")};
        imagesByUrl.set(image.url, record);
        items.append(record.card);
        renderImage(record);
        queue.push(record);
      }
    }
    for (const record of queue) {
      if (!current(run)) break;
      await translateRecord(run, record);
    }
    if (current(run)) showSummary();
  } catch (error) {
    if (current(run)) show(error.message || String(error));
  } finally {
    // An obsolete finally must not unlock controls owned by a newer run.
    if (current(run)) {
      activeRun = null;
      scanButton.disabled = false;
      updateRetryButtons();
    }
  }
}

scanButton.addEventListener("click", () => scan());
// permissions.request must run directly in the click handler for Chrome's user gesture.
grantButton.addEventListener("click", () => {
  const request = pendingPermission;
  if (!request) return;
  return chrome.permissions.request({origins: [request.pattern]}).then(async allowed => {
    if (request !== pendingPermission || request.generation !== generation) return;
    const tab = await activeMangaTab();
    if (request !== pendingPermission || request.generation !== generation) return;
    if (tab.id !== request.tabId || tab.url !== request.pageUrl) {
      reset("เปลี่ยนแท็บหรือหน้าแล้ว กดแปลภาพที่เห็นอีกครั้ง");
      return;
    }
    if (!allowed) {
      show("ยังไม่ได้อนุญาตเว็บไซต์นี้ จึงไม่สามารถอ่านรูปในหน้านี้ได้");
      return;
    }
    clearPendingPermission();
    await scan();
  }).catch(error => {
    if (request === pendingPermission && request.generation === generation) show("ขอสิทธิ์เข้าถึงเว็บไม่สำเร็จ: " + (error.message || error));
  });
});

chrome.tabs.onActivated.addListener(info => {
  if (source && info.windowId === source.windowId && info.tabId !== source.id) {
    reset("เปลี่ยนแท็บแล้ว กดแปลภาพที่เห็นเพื่อเริ่มบริบทใหม่");
  }
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (source?.id === tabId && (change.status === "loading" || (change.url && change.url !== source.url))) {
    reset("หน้าเปลี่ยนหรือโหลดใหม่แล้ว กดแปลภาพที่เห็นเพื่อเริ่มบริบทใหม่");
  }
});
chrome.tabs.onRemoved.addListener(tabId => {
  if (source?.id === tabId) reset("ปิดแท็บต้นฉบับแล้ว กรุณาเปิดหน้ามังงะ");
});
document.getElementById("reset").addEventListener("click", () => reset("เริ่มใหม่แล้ว"));
clearButton.addEventListener("click", async () => {
  if (clearing) return;
  clearing = true;
  clearButton.disabled = true;
  reset("กำลังลบคำแปลและคำแก้ไขที่บันทึกไว้…");
  try {
    const reply = await chrome.runtime.sendMessage({type: "MANGA_READER_CLEAR_CACHE"});
    if (!reply?.ok) throw new Error(reply?.error || "ลบข้อมูลไม่สำเร็จ กรุณาลองอีกครั้ง");
    show("ลบคำแปลและคำแก้ไขที่บันทึกไว้ทั้งหมดแล้ว");
  } catch (error) { show(error.message || String(error)); }
  finally {
    clearing = false;
    clearButton.disabled = false;
    scanButton.disabled = Boolean(activeRun);
  }
});
chrome.storage.onChanged.addListener((changes, area) => {
  const change = changes.mangaReaderCacheV1;
  if (area === "local" && change?.oldValue?.epoch && change.oldValue.epoch !== change.newValue?.epoch) {
    reset("ข้อมูลที่บันทึกไว้ถูกลบแล้ว กดแปลภาพที่เห็นเพื่อเริ่มใหม่");
  }
});
document.getElementById("settings").addEventListener("click", () => chrome.runtime.openOptionsPage());
