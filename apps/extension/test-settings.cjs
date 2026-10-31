const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const base = "apps/extension/";
const tick = () => new Promise(resolve => setImmediate(resolve));
async function settle() { for (let i = 0; i < 4; i++) await tick(); }
const reply = (status, body = {}) => ({status, ok: status >= 200 && status < 300, json: async () => structuredClone(body)});
const remembered = () => ({mangaCapability: "generated-reader", mangaSettingsCapability: "generated-manager",
  mangaReaderAppearance: {theme: "dark"}, mangaReaderCache: {entries: ["generated dialogue"]}});

function harness(file = "options", config = {}) {
  const values = structuredClone(config.values || {}), calls = [], tabs = [], forms = [], elements = new Map();
  const storageListeners = [], windowListeners = new Map();
  let failStorage = false;
  class Element {
    constructor(tag = "div") { this.tagName = tag; this.listeners = {}; this.textContent = ""; this.value = "";
      this.hidden = false; this.checked = false; this.disabled = false; this.dataset = {}; this.children = []; }
    addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); }
    async emit(event) { await Promise.all((this.listeners[event] || []).map(fn => fn({target: this, preventDefault() {}}))); }
    focus() { this.focused = true; }
    append(child) { this.children.push(child); }
    remove() { this.removed = true; }
    submit() { forms.push({method: this.method, action: this.action, fields: this.children.map(child => ({name: child.name, value: child.value}))}); }
  }
  const html = fs.readFileSync(base + file + ".html", "utf8");
  for (const match of html.matchAll(/<([a-z-]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]);
    element.hidden = /\bhidden\b/.test(match[0]); element.disabled = /\bdisabled\b/.test(match[0]);
    elements.set(match[2], element);
  }
  const local = {
    async setAccessLevel() { if (config.restrictFails) throw Error("generated storage error"); },
    async get(keys) { return Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, structuredClone(values[key])])); },
    async set(data) {
      if (failStorage) throw Error("generated quota error");
      Object.assign(values, structuredClone(data));
      for (const listener of storageListeners) listener(Object.fromEntries(Object.keys(data).map(key => [key, {}])), "local");
    },
    async remove(keys) {
      for (const key of keys) delete values[key];
      for (const listener of storageListeners) listener(Object.fromEntries(keys.map(key => [key, {}])), "local");
    }
  };
  const document = {hidden: false, body: new Element("body"), addEventListener() {},
    getElementById(id) { assert(elements.has(id), "actual HTML must contain " + id); return elements.get(id); },
    createElement(tag) { return new Element(tag); },
    querySelector(selector) { return document.body.children.find(child => child.tagName === selector && !child.removed); }};
  const context = vm.createContext({document, AbortSignal, console,
    window: {addEventListener(event, handler) { windowListeners.set(event, handler); }},
    navigator: {clipboard: {async writeText() {}}},
    chrome: {storage: {local, onChanged: {addListener(fn) { storageListeners.push(fn); }}},
      runtime: {getURL: path => "chrome-extension://" + "a".repeat(32) + "/" + path, async openOptionsPage() {}},
      tabs: {async create(tab) { tabs.push(tab); }}},
    fetch: async (url, options) => {
      const path = new URL(url).pathname;
      calls.push({path, url, options});
      if (config.fetch) { const result = await config.fetch(path, options); if (result) return result; }
      if (config.offline) throw Error("generated offline error");
      if (path === "/health") return reply(200, {status: "ok", provider: config.provider || "chatgpt_oauth"});
      if (path === "/api/v1/provider/status") return reply(config.readerStatus || 200,
        {connected: true, plan_usage_enabled: true, model: "vision-test", ...config.account});
      if (path === "/api/v1/settings/status") return reply(config.managerStatus || 200, {authorized: true});
      if (path === "/api/v1/pair/redeem") return reply(config.pairStatus || 200, config.pairResponse || {token: "generated-new-reader", settings_token: "generated-new-manager"});
      if (path === "/api/v1/pair/revoke") return reply(config.revokeStatus || 200, {revoked: true});
      if (path === "/api/v1/settings/ticket") return reply(config.ticketStatus || 200, {ticket: "generated-once-ticket".repeat(2)});
      throw Error("Unexpected request: " + path);
    }
  });
  vm.runInContext(fs.readFileSync(base + file + ".js", "utf8"), context, {filename: file + ".js"});
  return {elements, values, calls, tabs, forms, local, document, context,
    el: id => elements.get(id), failWrites: () => { failStorage = true; },
    async focus() { await windowListeners.get("focus")?.(); await settle(); },
    hide() { windowListeners.get("pagehide")?.(); }};
}

async function ready(config = {}) { const app = harness("options", config); await settle(); return app; }
async function pair(app) { app.el("pair-code").value = "GENERATED-ONE-TIME"; app.el("allow-settings").checked = true; await app.el("pair-form").emit("submit"); await settle(); }

// The real scripts run against HTML-derived controls and generated Chrome APIs.
test("Settings shows offline recovery while preserving remembered pairing", async () => {
  const app = await ready({offline: true, values: remembered()});
  assert.match(app.el("summary").textContent, /เปิดระบบแปล/);
  assert.equal(app.el("offline-help").hidden, false);
  assert.equal(app.el("forget").hidden, false);
  assert.equal(app.el("connect").disabled, true);
  assert.equal(app.values.mangaSettingsCapability, "generated-manager");
  assert(app.calls.every(call => call.path === "/health"));
});

test("first use offers pairing with unchecked management consent", async () => {
  const app = await ready();
  assert.equal(app.el("pair-section").hidden, false);
  assert.equal(app.el("allow-settings").checked, false);
  assert.equal(app.el("connect").disabled, true);
  await app.el("pair-form").emit("submit");
  assert.match(app.el("status").textContent, /ยืนยันสิทธิ์/);
  assert(!app.calls.some(call => call.path.includes("redeem")));
});

test("remembered authority shows readable readiness and opens an extension launch tab", async () => {
  const app = await ready({values: remembered()});
  assert.match(app.el("summary").textContent, /ตั้งค่าครบแล้ว.*ยังไม่ได้ทดสอบแปลจริง/);
  assert.equal(app.el("connect").disabled, false);
  assert.equal(app.el("model-state").textContent, "vision-test");
  assert.equal(app.el("pair-section").hidden, true);
  await app.el("connect").emit("click");
  assert.match(app.tabs[0].url, /^chrome-extension:\/\/a+\/settings-launch.html$/);
  assert(!JSON.stringify([...app.elements.values()].map(el => el.textContent)).includes("generated-manager"));
  assert(!app.calls.some(call => call.path.includes("translate")));
});

test("terminal refresh failure offers reconnect without claiming readiness or losing pairing", async () => {
  const app = await ready({values: remembered(), account: {connected: false, plan_usage_enabled: false, reconnect_required: true}});
  assert.match(app.el("summary").textContent, /หมดอายุ/);
  assert.match(app.el("next-step").textContent, /เชื่อมต่อบัญชีเดิม/);
  assert.equal(app.el("connect").disabled, false);
  assert.equal(app.values.mangaCapability, "generated-reader");
  assert(!app.calls.some(call => call.path.includes("translate")));
});

for (const [name, account, pattern] of [
  ["disconnected", {connected: false, plan_usage_enabled: false}, /เชื่อมต่อ ChatGPT/],
  ["missing consent", {plan_usage_enabled: false}, /เชื่อมต่อ ChatGPT/],
  ["missing model", {model: null}, /เลือกโมเดล/]
]) test("Settings identifies the next action for " + name, async () => {
  const app = await ready({values: remembered(), account});
  assert.match(app.el("summary").textContent, pattern);
  assert.equal(app.el("connect").disabled, false);
});

test("mock provider is identified instead of promising ChatGPT readiness", async () => {
  const app = await ready({values: remembered(), provider: "mock"});
  assert.match(app.el("summary").textContent, /ตัวแปลทดสอบ/);
});

test("legacy reader pairing does not acquire Settings authority", async () => {
  const app = await ready({values: {mangaCapability: "generated-legacy"}});
  assert.equal(app.el("connect").disabled, true);
  assert.equal(app.el("pair-section").hidden, false);
  assert(!app.calls.some(call => call.path.includes("/settings/")));
});

test("revoked pairing cannot leave management enabled", async () => {
  const app = await ready({values: remembered(), readerStatus: 401});
  assert.match(app.el("pair-state").textContent, /หมดสิทธิ์/);
  assert.equal(app.el("connect").disabled, true);
  assert.equal(app.el("pair-section").hidden, false);
});

test("successful pair persists separate credentials and survives reopening", async () => {
  const app = await ready({values: {mangaReaderCache: {entries: ["generated dialogue"]}}});
  await pair(app);
  assert.equal(app.values.mangaCapability, "generated-new-reader");
  assert.equal(app.values.mangaSettingsCapability, "generated-new-manager");
  assert.equal(app.values.mangaReaderCache.entries.length, 1);
  assert.equal(app.el("pair-code").value, "");
  assert.equal(app.el("allow-settings").checked, false);
  assert.equal(app.el("connect").disabled, false);
  const reopened = await ready({values: app.values});
  assert.equal(reopened.el("connect").disabled, false);
  const submitted = app.calls.find(call => call.path.includes("redeem"));
  assert.equal(JSON.parse(submitted.options.body).allow_settings, true);
});

test("redeeming a legacy code clears an old local management credential", async () => {
  const app = await ready({values: remembered(), pairResponse: {token: "generated-legacy"}});
  await pair(app);
  assert.equal(app.values.mangaSettingsCapability, null);
  assert.equal(app.el("connect").disabled, true);
  assert.equal(app.el("pair-section").hidden, false);
});

for (const [code, pattern] of [[403, /หมดอายุ/], [429, /รอหนึ่งนาที/]])
  test("pair failure " + code + " has an actionable message and keeps prior credentials", async () => {
    const app = await ready({values: remembered(), pairStatus: code});
    await pair(app);
    assert.match(app.el("status").textContent, pattern);
    assert.equal(app.values.mangaCapability, "generated-reader");
    assert.equal(app.values.mangaSettingsCapability, "generated-manager");
  });

test("storage failure never reports a successful remembered pairing", async () => {
  const app = await ready(); app.failWrites(); await pair(app);
  assert.match(app.el("status").textContent, /บันทึกสิทธิ์ในเบราว์เซอร์ไม่สำเร็จ/);
  assert.equal(app.el("status").dataset.state, "error");
  assert.equal(app.values.mangaCapability, undefined);
  assert.equal(app.el("pair-code").value, "");
});

test("re-pair form remains visible when returning from Terminal", async () => {
  const app = await ready({values: remembered()});
  await app.el("re-pair").emit("click"); await app.focus();
  assert.equal(app.el("pair-section").hidden, false);
});

test("revocation removes only pairing and keeps saved translations and appearance", async () => {
  const app = await ready({values: remembered()});
  await app.el("unpair").emit("click"); await settle();
  assert.equal(app.values.mangaCapability, undefined);
  assert.equal(app.values.mangaSettingsCapability, undefined);
  assert.deepEqual(app.values.mangaReaderAppearance, {theme: "dark"});
  assert.equal(app.values.mangaReaderCache.entries.length, 1);
  assert.equal(app.el("connect").disabled, true);
  assert.equal(app.el("pair-section").hidden, false);
  assert(app.calls.some(call => call.path === "/api/v1/pair/revoke"));
});

test("failed remote revocation retains credentials and offers explicitly local forgetting", async () => {
  const app = await ready({values: remembered(), revokeStatus: 503});
  await app.el("unpair").emit("click"); await settle();
  assert.equal(app.values.mangaSettingsCapability, "generated-manager");
  assert.equal(app.el("forget").hidden, false);
  await app.el("forget").emit("click"); await settle();
  assert.match(app.el("status").textContent, /ฝั่งระบบยังไม่ถูกถอน/);
  assert.equal(app.values.mangaCapability, undefined);
  assert.equal(app.values.mangaSettingsCapability, undefined);
  assert.equal(app.values.mangaReaderCache.entries.length, 1);
});

test("a late status reply cannot restore readiness after revocation", async () => {
  let resolve;
  let pending = false;
  const app = await ready({values: remembered(), fetch(path) {
    if (path === "/api/v1/provider/status" && pending) {
      pending = false;
      return new Promise(done => { resolve = done; });
    }
  }});
  pending = true;
  const check = app.el("check").emit("click"); await settle();
  const revoke = app.el("unpair").emit("click"); await settle();
  resolve(reply(200, {connected: true, plan_usage_enabled: true, model: "old-model"}));
  await Promise.all([check, revoke]); await settle();
  assert.equal(app.el("connect").disabled, true);
  assert.match(app.el("summary").textContent, /เริ่มจากจับคู่/);
  assert.notEqual(app.el("model-state").textContent, "old-model");
});

test("launch uses a one-use ticket in a POST body and removes it on pagehide", async () => {
  const app = harness("settings-launch", {values: remembered()}); await settle();
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].path, "/api/v1/settings/ticket");
  assert.equal(app.calls[0].options.headers.Authorization, "Bearer generated-manager");
  assert.equal(app.forms[0].method, "post");
  assert.equal(app.forms[0].action, "http://127.0.0.1:8000/auth/extension-session");
  assert.deepEqual(app.forms[0].fields, [{name: "ticket", value: "generated-once-ticket".repeat(2)}]);
  assert(!app.forms[0].action.includes("generated"));
  assert.equal(app.document.body.children[0].removed, undefined);
  app.hide();
  assert.equal(app.document.body.children[0].removed, true);
});

test("launch without management pairing sends no request", async () => {
  const app = harness("settings-launch"); await settle();
  assert.equal(app.calls.length, 0);
  assert.match(app.el("launch-status").textContent, /กลับไปจับคู่/);
});

test("revoked management cannot create a browser session", async () => {
  const app = harness("settings-launch", {values: remembered(), ticketStatus: 401}); await settle();
  assert.equal(app.forms.length, 0);
  assert.match(app.el("launch-status").textContent, /ถูกยกเลิก/);
});

test("launch network failure offers retry and never exposes a credential", async () => {
  const app = harness("settings-launch", {values: remembered(), offline: true}); await settle();
  assert.equal(app.forms.length, 0);
  assert.equal(app.el("retry").hidden, false);
  assert(!app.el("launch-status").textContent.includes("generated-manager"));
});

test("revocation falls back to the reader if the remembered management credential is stale", async () => {
  const app = await ready({values: remembered(), fetch(path, options) {
    if (path === "/api/v1/pair/revoke") return reply(options.headers.Authorization === "Bearer generated-manager" ? 401 : 200);
  }});
  await app.el("unpair").emit("click"); await settle();
  assert.equal(app.calls.filter(call => call.path === "/api/v1/pair/revoke").length, 2);
  assert.equal(app.values.mangaCapability, undefined);
  assert.equal(app.values.mangaSettingsCapability, undefined);
});
