/* Non-destructive Reader with bounded local persistence owned by the worker. */
const status = document.getElementById("status");
const items = document.getElementById("items");
const scanButton = document.getElementById("scan");
const grantButton = document.getElementById("grant");
const clearButton = document.getElementById("clear-cache");
const emptyState = document.getElementById("empty-state");
const readingCount = document.getElementById("reading-count");
const sourceLabel = document.getElementById("source-label");
const menu = document.getElementById("reader-menu");
const sourceToggle = document.getElementById("show-source");
const themeToggle = document.getElementById("theme");
const smallerButton = document.getElementById("font-smaller");
const largerButton = document.getElementById("font-larger");
const imagesByUrl = new Map();
let generation = 0;
let source = null;
let activeRun = null;
let pendingPermission = null;
let clearing = false;
let appearanceTouched = false;
let modelPicker = null;
const appearance = {theme: "light", fontSize: 19, showSource: false};

function applyAppearance() {
  document.documentElement.dataset.theme = appearance.theme;
  document.documentElement.dataset.source = appearance.showSource ? "visible" : "hidden";
  document.documentElement.style.setProperty("--reader-font-size", appearance.fontSize + "px");
  sourceToggle.setAttribute("aria-pressed", String(appearance.showSource));
  themeToggle.setAttribute("aria-pressed", String(appearance.theme === "dark"));
  smallerButton.disabled = appearance.fontSize <= 16;
  largerButton.disabled = appearance.fontSize >= 25;
}
function changeAppearance(change) {
  appearanceTouched = true;
  Object.assign(appearance, change);
  applyAppearance();
  chrome.storage.local.set({mangaReaderAppearance: {...appearance}}).catch(() => {});
}
applyAppearance();
chrome.storage.local.get("mangaReaderAppearance").then(({mangaReaderAppearance: saved}) => {
  if (appearanceTouched || !saved) return;
  if (saved.theme === "dark" || saved.theme === "light") appearance.theme = saved.theme;
  if (Number.isInteger(saved.fontSize) && saved.fontSize >= 16 && saved.fontSize <= 25) appearance.fontSize = saved.fontSize;
  if (typeof saved.showSource === "boolean") appearance.showSource = saved.showSource;
  applyAppearance();
}).catch(() => {});
sourceToggle.addEventListener("click", () => changeAppearance({showSource: !appearance.showSource}));
themeToggle.addEventListener("click", () => changeAppearance({theme: appearance.theme === "light" ? "dark" : "light"}));
smallerButton.addEventListener("click", () => changeAppearance({fontSize: Math.max(16, appearance.fontSize - 1)}));
largerButton.addEventListener("click", () => changeAppearance({fontSize: Math.min(25, appearance.fontSize + 1)}));

function updateReaderUi() {
  const count = [...imagesByUrl.values()].filter(r => r.state === "success").reduce((sum, r) => sum + r.regions.length, 0);
  emptyState.hidden = imagesByUrl.size > 0;
  items.hidden = imagesByUrl.size === 0;
  readingCount.textContent = count ? count + " บทสนทนา" : "พร้อมอ่าน";
  sourceLabel.textContent = source ? new URL(source.url).hostname : "เลือกแท็บมังงะเพื่อเริ่มอ่าน";
}
function setScanDisabled(disabled) {
  scanButton.disabled = disabled || Boolean(modelPicker?.saving);
  scanButton.setAttribute("aria-busy", String(scanButton.disabled));
  grantButton.disabled = Boolean(modelPicker?.saving);
  clearButton.disabled = clearing || Boolean(modelPicker?.saving);
  items.setAttribute("aria-busy", String(Boolean(activeRun)));
  modelPicker?.setReaderBusy(Boolean(activeRun) || clearing);
}

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
  setScanDisabled(clearing);
  updateReaderUi();
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
  const heading = element("div", "dialogue-heading");
  const label = element("small", "dialogue-number", String(index + 1).padStart(2, "0"));
  label.setAttribute("aria-label", "บทสนทนา " + (index + 1));
  const original = element("p", "source", r.source_text);
  const originalGroup = element("div", "source-group");
  originalGroup.append(element("small", "source-label", "ต้นฉบับอังกฤษ"), original);
  const translated = element("p", "translation", r.translated_text);
  const edit = element("button", "edit-button", "แก้คำแปล");
  edit.addEventListener("click", () => {
    if (activeRun) { show("รอแปลภาพในคิวให้เสร็จก่อนแก้คำแปล"); return; }
    if (card.querySelector("textarea")) return;
    const editor = element("div", "editor");
    const input = document.createElement("textarea");
    input.setAttribute("aria-label", "แก้คำแปลบทสนทนา " + (index + 1));
    input.maxLength = 1000;
    input.value = translated.textContent;
    const save = element("button", "save-button", "บันทึก");
    const cancel = element("button", "cancel-button", "ยกเลิก");
    const actions = element("div", "editor-actions");
    const errorMessage = element("p", "editor-error");
    errorMessage.setAttribute("role", "status");
    errorMessage.hidden = true;
    const close = () => { editor.remove(); translated.hidden = false; edit.disabled = false; edit.focus(); };
    const fail = message => { errorMessage.textContent = message; errorMessage.hidden = false; show(message); };
    cancel.addEventListener("click", close);
    save.addEventListener("click", async () => {
      const epoch = generation, key = record.cacheKey, text = input.value;
      if (!key || !text.trim() || text.length > 1000) {
        fail("ยังบันทึกไม่ได้: ต้องมีคำแปลที่บันทึกไว้ และข้อความไม่เกิน 1000 ตัวอักษร");
        return;
      }
      save.disabled = true;
      cancel.disabled = true;
      errorMessage.hidden = true;
      try {
        const reply = await chrome.runtime.sendMessage({type: "MANGA_READER_SAVE_EDIT", key, index, text, epoch: record.cacheEpoch});
        if (epoch !== generation || imagesByUrl.get(record.url) !== record || record.cacheKey !== key) return;
        if (!reply?.ok) throw new Error(reply?.error || "บันทึกคำแก้ไขไม่สำเร็จ กรุณาลองอีกครั้ง");
        translated.textContent = text;
        r.translated_text = text;
        close();
        show("บันทึกคำแก้ไขในเครื่องแล้ว");
      } catch (error) {
        if (epoch === generation) fail(error.message || String(error));
      } finally { save.disabled = false; cancel.disabled = false; }
    });
    actions.append(save, cancel);
    editor.append(input, errorMessage, actions);
    card.append(editor);
    translated.hidden = true;
    edit.disabled = true;
    input.focus();
  });
  heading.append(label, edit);
  card.append(heading, translated, originalGroup);
  record.card.append(card);
}

function renderImage(record) {
  record.card.dataset.state = record.state;
  const heading = element("header", "image-heading");
  heading.append(element("h2", "image-title", "ภาพ " + (record.index + 1)));
  if (record.state === "success") heading.append(element("span", "image-count", record.regions.length + " บทสนทนา"));
  if (record.cacheHit && (record.state === "success" || record.state === "empty")) {
    const badge = element("span", "image-badge", "บันทึกไว้");
    badge.setAttribute("title", "ใช้คำแปลที่บันทึกไว้");
    heading.append(badge);
  }
  record.card.replaceChildren(heading);
  if (record.notice) record.card.append(element("div", "image-notice", record.notice));
  if (record.state === "success") {
    const locate = element("button", "locate-button", "ไปยังภาพ");
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
    heading.append(locate);
    record.regions.forEach((r, index) => renderDialogue(record, r, index));
  } else {
    const messages = {queued: "รอแปล", loading: "กำลังแปล", empty: "ไม่พบบทสนทนาที่อ่านได้", error: "แปลไม่สำเร็จ: " + record.error};
    record.card.append(element("div", "image-status", messages[record.state]));
    if (record.state === "error") {
      const retry = element("button", "retry-button", "ลองใหม่");
      retry.disabled = Boolean(activeRun) || Boolean(modelPicker?.saving);
      retry.addEventListener("click", () => scan(record));
      record.card.append(retry);
    }
  }
  updateReaderUi();
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
  const parts = ["แปลแล้ว " + count("success") + " ภาพ"];
  if (count("empty")) parts.push("ไม่พบข้อความ " + count("empty") + " ภาพ");
  if (count("error")) parts.push("ล้มเหลว " + count("error") + " ภาพ");
  show(parts.join(" · "));
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
      pageUrl: source.url, context: previousContext(record), profile: run.profile || ""
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
    run.settingsChanged = Boolean(reply?.settingsChanged);
  } else {
    if (/^[a-f0-9]{64}$/.test(reply.data.profile)) run.profile = reply.data.profile;
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
  if (activeRun || clearing || modelPicker?.saving) return;
  if (items.querySelector("textarea")) { show("บันทึกหรือยกเลิกคำแก้ไขก่อนแปลภาพถัดไป"); return; }
  // Capture the generation before the first await, including tab/permission setup.
  const run = {generation};
  activeRun = run;
  setScanDisabled(true);
  updateRetryButtons();
  try {
    const tab = await activeMangaTab();
    if (!current(run)) return;
    if (!sameSource(source, tab)) {
      reset("เริ่มบริบทสำหรับหน้านี้");
      source = tab;
      updateReaderUi();
      run.generation = generation;
      activeRun = run;
      setScanDisabled(true);
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
      if (!current(run)) break;
      if (run.settingsChanged) {
        for (const remaining of queue) if (remaining.state === "queued") {
          remaining.state = "error";
          remaining.error = "ยังไม่ได้ส่งแปล เนื่องจากโมเดลหรือการตั้งค่าเปลี่ยนแล้ว";
          renderImage(remaining);
        }
        break;
      }
    }
    if (current(run)) {
      if (run.settingsChanged) show("โมเดลหรือการตั้งค่าเปลี่ยนแล้ว หยุดคิวไว้ กดลองใหม่ทีละภาพเมื่อพร้อม");
      else showSummary();
    }
  } catch (error) {
    if (current(run)) show(error.message || String(error));
  } finally {
    // An obsolete finally must not unlock controls owned by a newer run.
    if (current(run)) {
      activeRun = null;
      setScanDisabled(false);
      updateRetryButtons();
      if (run.settingsChanged) modelPicker?.refreshStatus();
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
  if (clearing || modelPicker?.saving) return;
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
    setScanDisabled(Boolean(activeRun));
  }
});
chrome.storage.onChanged.addListener((changes, area) => {
  const change = changes.mangaReaderCacheV1;
  if (area === "local" && change?.oldValue?.epoch && change.oldValue.epoch !== change.newValue?.epoch) {
    reset("ข้อมูลที่บันทึกไว้ถูกลบแล้ว กดแปลภาพที่เห็นเพื่อเริ่มใหม่");
  }
});
document.getElementById("settings").addEventListener("click", () => chrome.runtime.openOptionsPage());
for (const id of ["settings", "reset", "clear-cache"]) {
  document.getElementById(id).addEventListener("click", () => { menu.open = false; });
}
menu.addEventListener("keydown", event => {
  if (event.key === "Escape") { menu.open = false; menu.querySelector("summary")?.focus(); }
});
updateReaderUi();
modelPicker = new ReaderModelPicker({onBusyChange: () => {
  setScanDisabled(Boolean(activeRun) || clearing);
  updateRetryButtons();
}});
