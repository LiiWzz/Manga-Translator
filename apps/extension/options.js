"use strict";
const GATEWAY = "http://127.0.0.1:8000";
const byId = id => document.getElementById(id);
let busy = false;
let refreshVersion = 0;
let checking = null;
let refreshRequested = false;
let allowLocalForget = false;
let pairingRequested = false;

async function request(path, {token, ...options} = {}) {
  return fetch(GATEWAY + path, {cache: "no-store", credentials: "omit", redirect: "error",
    signal: AbortSignal.timeout(5000), ...options,
    headers: {...(token ? {Authorization: "Bearer " + token} : {}), ...options.headers}});
}
function feedback(text, error = false) {
  byId("status").textContent = text;
  byId("status").dataset.state = error ? "error" : "ok";
}
function row(id, text) { byId(id).textContent = text; }
function showPairing() {
  pairingRequested = true;
  byId("pair-section").hidden = false;
  byId("pair-code").focus();
}
function setBusy(value) {
  busy = value;
  for (const id of ["pair", "unpair", "forget", "check", "re-pair"]) byId(id).disabled = value;
  if (value) byId("connect").disabled = true;
}

async function refresh() {
  if (busy) return;
  if (checking) { refreshRequested = true; return checking; }
  const version = ++refreshVersion;
  const current = () => version === refreshVersion && !busy;
  checking = (async () => {
    let saved;
    try { saved = await chrome.storage.local.get(["mangaCapability", "mangaSettingsCapability"]); }
    catch {
      if (current()) { row("summary", "อ่านการตั้งค่าไม่ได้"); feedback("เปิดพื้นที่จัดเก็บของส่วนขยายไม่ได้ กรุณาโหลดส่วนขยายใหม่แล้วลองอีกครั้ง", true); }
      return;
    }
    const reader = saved.mangaCapability, manager = saved.mangaSettingsCapability;
    if (!current()) return;
    byId("connect").disabled = true;
    byId("connect").hidden = true;
    for (const id of ["account-row", "permission-row", "model-row"]) byId(id).hidden = !reader;
    row("pair-state", reader ? "บันทึกการจับคู่ไว้แล้ว" : "ยังไม่ได้จับคู่");
    for (const id of ["account-state", "permission-state", "model-state"]) row(id, "ยังไม่ได้ตรวจ");
    let health;
    try {
      const response = await request("/health");
      if (!response.ok) throw new Error("unavailable");
      health = await response.json();
      if (health.status !== "ok") throw new Error("unavailable");
    } catch {
      if (!current()) return;
      row("gateway-state", "ยังเชื่อมต่อไม่ได้"); row("summary", "เปิดระบบแปลก่อน");
      row("next-step", "ตรวจว่า Docker และระบบแปลกำลังทำงาน แล้วกดตรวจอีกครั้ง");
      byId("offline-help").hidden = false;
      byId("forget").hidden = byId("forget-help").hidden = !reader && !manager;
      byId("pair-section").hidden = true;
      return;
    }
    if (!current()) return;
    row("gateway-state", "เชื่อมต่อแล้ว");
    byId("offline-help").hidden = true;
    byId("forget").hidden = byId("forget-help").hidden = !allowLocalForget;
    if (!reader) {
      row("summary", "เริ่มจากจับคู่เครื่องนี้");
      row("next-step", "ทำขั้นตอนด้านล่างครั้งเดียว เพื่ออนุญาตการแปลและการจัดการ Settings");
      byId("pair-section").hidden = false;
      return;
    }
    try {
      const response = await request("/api/v1/provider/status", {token: reader});
      if (!current()) return;
      if (response.status === 401 || response.status === 403) {
        row("pair-state", "การจับคู่หมดสิทธิ์แล้ว"); row("summary", "จับคู่ใหม่เพื่อใช้งานต่อ");
        row("next-step", "รันคำสั่งและใช้รหัสใหม่ด้านล่าง บัญชีและคำแปลที่บันทึกไว้ยังอยู่");
        byId("pair-section").hidden = false;
        return;
      }
      if (!response.ok) throw new Error("status");
      const state = await response.json();
      let management = false;
      if (manager) {
        const access = await request("/api/v1/settings/status", {token: manager});
        if (!access.ok && access.status !== 401 && access.status !== 403) throw new Error("management");
        management = access.ok;
      }
      if (!current()) return;
      row("pair-state", management ? "จับคู่และจำสิทธิ์แล้ว" : "แปลได้ · ยังไม่มีสิทธิ์จัดการ Settings");
      row("account-state", state.connected ? "เชื่อมต่อแล้ว" : "ยังไม่ได้เชื่อมต่อ");
      row("permission-state", state.plan_usage_enabled ? "อนุญาตแล้ว" : "ยังไม่ได้อนุญาต");
      row("model-state", state.model || "ยังไม่ได้เลือก");
      byId("connect").disabled = !management;
      byId("connect").hidden = !management;
      byId("pair-section").hidden = management && !pairingRequested;
      if (!management) {
        row("summary", "จับคู่ใหม่เพื่อเปิด Settings ได้สะดวกขึ้น");
        row("next-step", "การจับคู่เดิมยังใช้แปลได้ รหัสจากคำสั่งด้านล่างจะเพิ่มสิทธิ์จัดการการเชื่อมต่อเมื่อคุณยินยอม");
      } else if (health.provider !== "chatgpt_oauth") {
        row("summary", "ระบบกำลังใช้ตัวแปลทดสอบหรือผู้ให้บริการอื่น");
        row("next-step", "หากต้องการใช้ ChatGPT ให้ตั้ง TRANSLATOR_PROVIDER=chatgpt_oauth แล้วเริ่มระบบแปลใหม่");
      } else if (state.reconnect_required) {
        row("account-state", "ต้องเชื่อมต่อใหม่");
        row("summary", "การเชื่อมต่อ ChatGPT หมดอายุ");
        row("next-step", "กดจัดการการเชื่อมต่อ แล้วเลือกเชื่อมต่อบัญชีเดิมอีกครั้ง");
      } else if (!state.connected || !state.plan_usage_enabled) {
        row("summary", "เชื่อมต่อ ChatGPT เป็นขั้นตอนถัดไป");
        row("next-step", "กดจัดการการเชื่อมต่อ แล้วเข้าสู่ระบบและตรวจสอบการอนุญาตใช้แผน ChatGPT");
      } else if (!state.model) {
        row("summary", "เลือกโมเดลอีกขั้นตอนเดียว");
        row("next-step", "กดจัดการการเชื่อมต่อ แล้วเลือกโมเดลที่รองรับภาพจากรายการ");
      } else {
        row("summary", "ตั้งค่าครบแล้ว · ยังไม่ได้ทดสอบแปลจริง");
        row("next-step", "กลับไปแท็บมังงะ เปิด Reader แล้วกด “แปลภาพที่เห็น” การแปลจริงอาจใช้โควตาบัญชี");
      }
    } catch {
      if (!current()) return;
      row("summary", "ตรวจสถานะไม่สำเร็จ");
      row("next-step", "การจับคู่ที่บันทึกไว้ยังอยู่ กดตรวจอีกครั้งเมื่อระบบพร้อม");
      byId("forget").hidden = byId("forget-help").hidden = false;
    }
  })();
  try { await checking; }
  finally {
    checking = null;
    if (refreshRequested) { refreshRequested = false; await refresh(); }
  }
}

byId("connect").addEventListener("click", async () => {
  try { await chrome.tabs.create({url: chrome.runtime.getURL("settings-launch.html")}); }
  catch { feedback("เปิดหน้าการเชื่อมต่อไม่ได้ กรุณาลองอีกครั้ง", true); }
});
byId("pair-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  const code = byId("pair-code").value.trim();
  if (!code || !byId("allow-settings").checked) {
    feedback("กรอกรหัสและยืนยันสิทธิ์การแปลกับการจัดการ Settings ก่อนจับคู่", true); return;
  }
  ++refreshVersion; setBusy(true);
  try {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    const response = await request("/api/v1/pair/redeem", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({code, allow_settings: true})});
    if (!response.ok) {
      const message = response.status === 429 ? "ลองหลายครั้งเกินไป รอหนึ่งนาทีแล้วลองใหม่"
        : response.status === 409 ? "ต้องยืนยันสิทธิ์จัดการ Settings ก่อนจับคู่"
          : "รหัสไม่ถูกต้องหรือหมดอายุ รันคำสั่งเพื่อสร้างรหัสใหม่";
      feedback(message, true); return;
    }
    const data = await response.json();
    if (typeof data.token !== "string" || !data.token) throw new Error("credentials");
    byId("pair-code").value = "";
    try {
      await chrome.storage.local.set({mangaCapability: data.token,
        mangaSettingsCapability: typeof data.settings_token === "string" ? data.settings_token : null});
    } catch {
      feedback("จับคู่ที่ระบบแล้ว แต่บันทึกสิทธิ์ในเบราว์เซอร์ไม่สำเร็จ กรุณาสร้างรหัสใหม่และจับคู่อีกครั้ง", true); return;
    }
    byId("allow-settings").checked = false;
    pairingRequested = false;
    feedback(data.settings_token ? "จับคู่และจำสิทธิ์แล้ว เปิดจัดการการเชื่อมต่อได้เลย" : "จับคู่เพื่อแปลแล้ว หากต้องการจัดการ Settings ให้ใช้รหัสจากคำสั่งด้านบน");
  } catch { feedback("จับคู่ไม่สำเร็จ ตรวจระบบแปลแล้วลองอีกครั้ง หากรหัสถูกใช้แล้วให้สร้างรหัสใหม่", true); }
  finally { setBusy(false); await refresh(); }
});

byId("unpair").addEventListener("click", async () => {
  if (busy) return;
  ++refreshVersion; setBusy(true);
  try {
    const {mangaCapability, mangaSettingsCapability} = await chrome.storage.local.get(["mangaCapability", "mangaSettingsCapability"]);
    for (const token of new Set([mangaSettingsCapability, mangaCapability].filter(Boolean))) {
      const response = await request("/api/v1/pair/revoke", {method: "POST", token});
      if (!response.ok && response.status !== 401) throw new Error("revoke");
      if (response.ok) break;
    }
    await chrome.storage.local.remove(["mangaCapability", "mangaSettingsCapability"]);
    allowLocalForget = false;
    feedback("ยกเลิกการจับคู่แล้ว บัญชี ChatGPT และคำแปลที่บันทึกไว้ยังอยู่");
  } catch {
    allowLocalForget = true;
    feedback("ยังยกเลิกการจับคู่ไม่สำเร็จ สิทธิ์ในเบราว์เซอร์ยังอยู่ ลองอีกครั้ง หรือเลือกลืมสิทธิ์เฉพาะในเบราว์เซอร์", true);
    byId("forget").hidden = byId("forget-help").hidden = false;
  } finally { setBusy(false); await refresh(); }
});
byId("forget").addEventListener("click", async () => {
  if (busy) return;
  ++refreshVersion; setBusy(true);
  try {
    await chrome.storage.local.remove(["mangaCapability", "mangaSettingsCapability"]);
    allowLocalForget = false;
    feedback("ลืมสิทธิ์ในเบราว์เซอร์แล้ว สิทธิ์ฝั่งระบบยังไม่ถูกถอน ให้จับคู่ใหม่เมื่อระบบกลับมา");
  } catch { feedback("ลบสิทธิ์ในเบราว์เซอร์ไม่สำเร็จ กรุณาลองอีกครั้ง", true); }
  finally { setBusy(false); await refresh(); }
});
byId("re-pair").addEventListener("click", showPairing);
byId("copy-command").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(byId("pair-command").textContent); feedback("คัดลอกคำสั่งแล้ว"); }
  catch { feedback("คัดลอกอัตโนมัติไม่ได้ เลือกและคัดลอกคำสั่งด้านบนได้เลย", true); }
});
byId("check").addEventListener("click", refresh);
window.addEventListener("focus", refresh);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes.mangaCapability || changes.mangaSettingsCapability)) { ++refreshVersion; refresh(); }
});
byId("debug").addEventListener("change", async event => {
  try { await chrome.storage.local.set({mangaDebug: event.target.checked}); }
  catch { event.target.checked = !event.target.checked; feedback("บันทึกค่าดีบักไม่สำเร็จ กรุณาลองอีกครั้ง", true); }
});
async function initialize() {
  try {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    const {mangaDebug} = await chrome.storage.local.get("mangaDebug");
    byId("debug").checked = Boolean(mangaDebug);
    await refresh();
  } catch { feedback("เปิดพื้นที่จัดเก็บที่ปลอดภัยไม่ได้ กรุณาโหลดส่วนขยายใหม่", true); }
}
initialize();
