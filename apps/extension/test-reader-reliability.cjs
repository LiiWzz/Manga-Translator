const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {test} = require("node:test");

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function event() {
  const listeners = [];
  return {
    addListener(listener) { listeners.push(listener); },
    async emit(...args) { await Promise.all(listeners.map(fn => fn(...args))); }
  };
}
class Element {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.ownText = "";
    this.dataset = {};
    this.attributes = {};
    this.style = {setProperty(name, value) { this[name] = value; }};
  }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get textContent() { return this.ownText + this.children.map(el => el.textContent).join(" "); }
  append(...children) { children.forEach(el => { el.parent = this; this.children.push(el); }); }
  replaceChildren(...children) { this.ownText = ""; this.children = []; this.append(...children); }
  remove() { this.parent.children = this.parent.children.filter(el => el !== this); }
  focus() {}
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async click() {
    if (!this.disabled) await Promise.all((this.listeners.click || []).map(fn => fn()));
  }
  async emit(name, event = {}) { await Promise.all((this.listeners[name] || []).map(fn => fn(event))); }
  querySelector(tag) { return descendants(this).find(el => el.tagName === tag) || null; }
}
function descendants(el) { return el.children.flatMap(child => [child, ...descendants(child)]); }
function harness({savedAppearance, modelAccess = false} = {}) {
  const elements = Object.fromEntries(["status", "items", "scan", "grant", "reset", "settings", "clear-cache",
    "empty-state", "reading-count", "source-label", "reader-menu", "show-source", "theme", "font-smaller", "font-larger",
    "model-picker", "model-summary", "model-current", "model-count", "model-select", "model-reload", "model-status", "model-settings"].map(id => [id, new Element()]));
  const root = new Element("html");
  const state = {
    savedAppearance,
    credentials: modelAccess ? {mangaCapability: "generated-reader", mangaSettingsCapability: "generated-manager"} : {},
    model: "vision-a", modelVersion: "a".repeat(64), modelCalls: [], windowEvents: {},
    catalog: [{slug: "vision-a", display_name: "Vision A"}, {slug: "vision-b", display_name: "Vision B"}],
    tab: {id: 1, windowId: 1, url: "https://reader.example/chapter/1"},
    images: [{index: 0, url: "https://reader.example/1.png"}],
    calls: [],
    translate: async () => reply(),
    permission: async () => true,
    requestPermission: async () => true,
    inject: async () => {},
    discover: null
  };
  const chrome = {
    tabs: {
      query: async () => [{...state.tab}], get: async () => ({...state.tab}),
      onActivated: event(), onUpdated: event(), onRemoved: event(),
      sendMessage: async (_id, message) => message.type === "MANGA_READER_DISCOVER"
        ? state.discover ? state.discover() : state.images : true
    },
    permissions: {contains: () => state.permission(), request: () => state.requestPermission()},
    scripting: {executeScript: () => state.inject()},
    storage: {onChanged: event(), local: {
      setAccessLevel: async () => {},
      get: async () => ({mangaReaderAppearance: state.savedAppearance, ...state.credentials}),
      set: async ({mangaReaderAppearance}) => { state.savedAppearance = mangaReaderAppearance; }
    }},
    runtime: {
      sendMessage: message => {
        if (message.type !== "MANGA_READER_TRANSLATE") return state.mutate ? state.mutate(message) : Promise.resolve({ok: true});
        state.calls.push(message);
        return state.translate(message);
      },
      openOptionsPage() {}
    }
  };
  const fetch = async (url, options = {}) => {
    const path = new URL(url).pathname;
    state.modelCalls.push({path, options});
    if (state.modelRequest) { const result = await state.modelRequest(path, options); if (result) return result; }
    const response = body => ({ok: true, status: 200, json: async () => body});
    if (path === "/api/v1/provider/status") return response({connected: true, plan_usage_enabled: true, model: state.model});
    if (path === "/api/v1/settings/models") return response({models: state.catalog, model: state.model, version: state.modelVersion});
    if (path === "/api/v1/settings/model") {
      state.model = JSON.parse(options.body).slug;
      state.modelVersion = "b".repeat(64);
      return response({model: state.model, version: state.modelVersion});
    }
    throw new Error("Unexpected model request");
  };
  vm.runInNewContext(fs.readFileSync("apps/extension/reader-models.js", "utf8") + "\n" + fs.readFileSync("apps/extension/reader-panel.js", "utf8"), {
    chrome, URL, AbortSignal, fetch, window: {addEventListener(name, handler) { (state.windowEvents[name] ||= event()).addListener(handler); }},
    document: {documentElement: root, getElementById: id => elements[id], createElement: tag => new Element(tag)}
  });
  return {
    state, chrome, elements, root,
    scan: () => elements.scan.click(),
    reset: () => elements.reset.click(),
    async openModels() { elements["model-picker"].open = true; await elements["model-picker"].emit("toggle"); await settle(); },
    async chooseModel(slug) { elements["model-select"].value = slug; await elements["model-select"].emit("change"); await settle(); },
    text: () => elements.items.textContent,
    retry: () => descendants(elements.items).find(el => el.tagName === "button" && el.textContent === "ลองใหม่")?.click()
  };
}
function reply(source = "HELLO", translated = "สวัสดี") {
  return {ok: true, data: {cache_key: "a".repeat(64), regions: [{source_text: source, translated_text: translated}]}};
}
async function settle() { for (let i = 0; i < 8; i++) await new Promise(setImmediate); }

test("failed image keeps its error and retries only on explicit request while success is revalidated", async () => {
  const h = harness();
  h.state.images.push({index: 1, url: "https://reader.example/2.png"});
  h.state.translate = async message => message.url.endsWith("1.png") ? reply() : {ok: false, error: "Image HTTP 503"};
  await h.scan();
  assert.match(h.text(), /Image HTTP 503/);
  assert.match(h.text(), /สวัสดี/);
  await h.scan();
  assert.equal(h.state.calls.length, 3, "scan revalidates success but must not retry failure");
  h.state.translate = async () => reply("BYE", "ลาก่อน");
  await h.retry();
  assert.equal(h.state.calls.length, 4);
  assert.match(h.state.calls[3].url, /2.png$/);
  assert.doesNotMatch(h.text(), /Image HTTP 503/);
  assert.match(h.text(), /ลาก่อน/);
});

test("transport exceptions are visible per image and do not stop other images", async () => {
  const h = harness();
  h.state.images.push({index: 1, url: "https://reader.example/2.png"});
  h.state.translate = async message => {
    if (message.url.endsWith("1.png")) throw new Error("Worker disconnected");
    return reply();
  };
  await h.scan();
  assert.match(h.text(), /Worker disconnected/);
  assert.match(h.text(), /สวัสดี/);
  assert.equal(h.state.calls.length, 2);
});

test("empty images are remembered and have a visible status", async () => {
  const h = harness();
  h.state.translate = async () => ({ok: true, data: {regions: []}});
  await h.scan();
  assert.match(h.text(), /ไม่พบ/);
  await h.scan();
  assert.equal(h.state.calls.length, 2, "empty images are revalidated before persistent reuse");
  assert.equal(h.elements.items.children.length, 1);
});

test("malformed successful responses become retryable image errors", async () => {
  const h = harness();
  h.state.translate = async () => ({ok: true, data: {}});
  await h.scan();
  assert.match(h.text(), /ลองใหม่/);
});

test("reset discards a late reply and stops the remaining queue", async () => {
  const h = harness(), pending = deferred();
  h.state.images.push({index: 1, url: "https://reader.example/2.png"});
  h.state.translate = () => pending.promise;
  const run = h.scan();
  await settle();
  assert.equal(h.state.calls.length, 1);
  await h.reset();
  pending.resolve(reply());
  await run;
  assert.equal(h.text(), "");
  assert.equal(h.state.calls.length, 1);
  assert.match(h.elements.status.textContent, /เริ่มใหม่/);
  h.state.translate = async () => reply();
  await h.scan();
  assert.equal(h.state.calls.length, 3, "new scan revalidates both visible images");
});

test("an older run cannot unlock the scan button while a new run is pending", async () => {
  const h = harness(), old = deferred(), current = deferred();
  h.state.translate = () => old.promise;
  const first = h.scan();
  await settle();
  await h.reset();
  h.state.translate = () => current.promise;
  const second = h.scan();
  await settle();
  assert.equal(h.state.calls.length, 2);
  old.resolve(reply("OLD", "เก่า"));
  await first;
  assert.equal(h.elements.scan.disabled, true);
  assert.doesNotMatch(h.text(), /เก่า/);
  current.resolve(reply("NEW", "ใหม่"));
  await second;
  assert.equal(h.elements.scan.disabled, false);
  assert.match(h.text(), /ใหม่/);
});

for (const stage of ["permission", "inject", "discover"]) {
  test(`reset during ${stage} prevents any translation request`, async () => {
    const h = harness(), pending = deferred();
    h.state[stage] = () => pending.promise;
    const run = h.scan();
    await settle();
    await h.reset();
    pending.resolve(stage === "discover" ? h.state.images : true);
    await run;
    assert.equal(h.state.calls.length, 0);
    assert.equal(h.text(), "");
    assert.match(h.elements.status.textContent, /เริ่มใหม่/);
  });
}

test("context is preserved within a chapter and isolated when the source changes", async () => {
  const h = harness();
  await h.scan();
  h.state.images = [{index: 1, url: "https://reader.example/2.png"}];
  await h.scan();
  assert.match(h.state.calls[1].context, /HELLO/);
  h.state.tab = {...h.state.tab, id: 2};
  await h.scan();
  assert.equal(h.state.calls[2].context, "");
  h.state.tab.url = "https://reader.example/chapter/2";
  await h.scan();
  assert.equal(h.state.calls[3].context, "");
});

for (const change of ["activation", "navigation", "reload", "removed"]) {
  test(`${change} invalidates pending replies and queued work`, async () => {
    const h = harness(), pending = deferred();
    h.state.images.push({index: 1, url: "https://reader.example/2.png"});
    h.state.translate = () => pending.promise;
    const run = h.scan();
    await settle();
    if (change === "activation") {
      h.state.tab = {...h.state.tab, id: 2};
      await h.chrome.tabs.onActivated.emit({tabId: 2, windowId: 1});
    } else if (change === "removed") {
      await h.chrome.tabs.onRemoved.emit(1);
    } else {
      if (change === "navigation") h.state.tab.url += "#chapter2";
      await h.chrome.tabs.onUpdated.emit(1, change === "reload" ? {status: "loading"} : {url: h.state.tab.url});
    }
    pending.resolve(reply());
    await run;
    assert.equal(h.text(), "");
    assert.equal(h.state.calls.length, 1);
  });
}

test("source changes without a delivered tab event are caught before using a reply", async () => {
  const h = harness(), pending = deferred();
  h.state.translate = () => pending.promise;
  const run = h.scan();
  await settle();
  h.state.tab.url += "/next";
  pending.resolve(reply());
  await run;
  assert.equal(h.text(), "");
});

test("a stale permission grant after reset cannot start scanning", async () => {
  const h = harness(), pending = deferred();
  h.state.permission = async () => false;
  await h.scan();
  h.state.requestPermission = () => pending.promise;
  const grant = h.elements.grant.click();
  await h.reset();
  h.state.permission = async () => true;
  pending.resolve(true);
  await grant;
  await settle();
  assert.equal(h.state.calls.length, 0);
});

test("retry of an earlier image excludes later dialogue from context", async () => {
  const h = harness();
  h.state.images.push({index: 1, url: "https://reader.example/2.png"});
  h.state.translate = async message => message.url.endsWith("1.png")
    ? {ok: false, error: "Retry later"} : reply("FUTURE", "ภายหลัง");
  await h.scan();
  h.state.translate = async () => reply();
  await h.retry();
  assert.equal(h.state.calls[2].context, "");
});

test("edits survive a scan and become context for the next image", async () => {
  const h = harness();
  await h.scan();
  await descendants(h.elements.items).find(el => el.tagName === "button" && el.textContent === "แก้คำแปล").click();
  h.elements.items.querySelector("textarea").value = "คำที่แก้ไข";
  await descendants(h.elements.items).find(el => el.tagName === "button" && el.textContent === "บันทึก").click();
  h.state.images = [{index: 1, url: "https://reader.example/2.png"}];
  await h.scan();
  assert.match(h.text(), /คำที่แก้ไข/);
  assert.match(h.state.calls[1].context, /คำที่แก้ไข/);
});

test("a pending grant for a different page cannot submit a translation", async () => {
  const h = harness(), pending = deferred();
  h.state.permission = async () => false;
  await h.scan();
  h.state.requestPermission = () => pending.promise;
  const grant = h.elements.grant.click();
  h.state.tab.url += "/next";
  h.state.permission = async () => true;
  pending.resolve(true);
  await grant;
  assert.equal(h.state.calls.length, 0);
});

test("an inaccessible source invalidates the session even without a tab event", async () => {
  const h = harness(), pending = deferred();
  h.state.translate = () => pending.promise;
  const run = h.scan();
  await settle();
  h.state.tab.url = "chrome://extensions/";
  pending.resolve(reply());
  await run;
  assert.equal(h.text(), "");
  assert.equal(h.elements.scan.disabled, false);
});

function contentHarness() {
  let listener;
  const state = {scrolled: [], location: {href: "https://reader.example/chapter/1"}};
  const image = name => ({
    currentSrc: "https://reader.example/" + name + ".png", complete: true,
    naturalWidth: 500, naturalHeight: 700,
    getBoundingClientRect: () => ({width: 500, top: 0, bottom: 700}),
    scrollIntoView: () => state.scrolled.push(name)
  });
  state.images = [image("original")];
  vm.runInNewContext(fs.readFileSync("apps/extension/reader-content.js", "utf8"), {
    window: {}, location: state.location, innerHeight: 800,
    document: {get images() { return state.images; }},
    chrome: {runtime: {onMessage: {addListener(fn) { listener = fn; }}}}
  });
  state.send = message => { let result; listener(message, {}, reply => { result = reply; }); return result; };
  state.image = image;
  return state;
}

test("locate uses image identity after lazy-loaded DOM insertion", () => {
  const h = contentHarness();
  h.images.unshift(h.image("inserted"));
  assert.equal(h.send({type: "MANGA_READER_LOCATE", pageUrl: h.location.href, url: "https://reader.example/original.png", index: 0}), true);
  assert.deepEqual(h.scrolled, ["original"]);
});

test("content discovery and locate reject a stale chapter URL", () => {
  const h = contentHarness(), pageUrl = h.location.href;
  h.location.href += "/next";
  assert.equal(h.send({type: "MANGA_READER_DISCOVER", pageUrl}), false);
  assert.equal(h.send({type: "MANGA_READER_LOCATE", pageUrl, url: h.images[0].currentSrc}), false);
  assert.deepEqual(h.scrolled, []);
});

function workerHarness({storage = {}} = {}) {
  let listener;
  const state = {
    tab: {id: 1, url: "https://reader.example/chapter/1", status: "complete"},
    active: true, fetched: [], beforeBlob: () => {},
    profile: "1".repeat(64), imageBytes: "generated-test-bytes", storage,
    message: {type: "MANGA_READER_TRANSLATE", tabId: 1, pageUrl: "https://reader.example/chapter/1", url: "https://reader.example/1.png", context: "prior dialogue"}
  };
  const context = vm.createContext({
    URL, FormData, console, crypto, TextEncoder, Uint8Array,
    importScripts: file => vm.runInContext(fs.readFileSync("apps/extension/" + file, "utf8"), context),
    chrome: {
      sidePanel: {setPanelBehavior: async () => {}},
      runtime: {id: "test-extension", onMessage: {addListener(fn) { listener = fn; }}},
      storage: {local: {
        setAccessLevel: async options => { state.accessLevel = options.accessLevel; },
        get: async keys => {
          const all = {mangaCapability: "test-only-local-capability", ...state.storage};
          return structuredClone(Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, all[key]])));
        },
        set: async data => {
          if (state.failStorage) throw new Error("Quota exceeded");
          Object.assign(state.storage, structuredClone(data));
        }
      }},
      tabs: {get: async () => ({...state.tab}), query: async () => state.active ? [{...state.tab}] : []}
    },
    fetch: async (url, options) => {
      state.fetched.push(url);
      if (url.startsWith("https:")) assert.equal(options.cache, "no-store");
      if (url.startsWith("https:")) return {
        ok: true, headers: new Headers({"content-type": "image/png"}),
        blob: async () => { await state.beforeBlob(); return new Blob([state.imageBytes], {type: "image/png"}); }
      };
      if (url.endsWith("/profile")) return state.profileResponse || {ok: true, json: async () => ({fingerprint: state.profile})};
      if (state.inference) return state.inference();
      return {ok: true, json: async () => ({regions: [{source_text: "HELLO", translated_text: "สวัสดี"}], profile: state.profile})};
    }
  });
  vm.runInContext(fs.readFileSync("apps/extension/background.js", "utf8"), context);
  state.send = (message = state.message, sender = {id: "test-extension", url: "chrome-extension://test-extension/reader-panel.html"}) => new Promise(resolve => listener(message, sender, resolve));
  return state;
}

test("worker submits a reader request only for the active source page", async () => {
  const h = workerHarness();
  assert.equal((await h.send()).ok, true);
  assert.equal(h.fetched.length, 3);
  assert.match(h.fetched[2], /reader\/translate$/);
  assert.equal(h.accessLevel, "TRUSTED_CONTEXTS");
});

for (const change of ["url", "inactive", "loading", "missing-page-url"]) {
  test(`worker rejects ${change} before fetching the image`, async () => {
    const h = workerHarness();
    if (change === "url") h.tab.url += "/next";
    if (change === "inactive") h.active = false;
    if (change === "loading") h.tab.status = "loading";
    if (change === "missing-page-url") delete h.message.pageUrl;
    assert.equal((await h.send()).ok, false);
    assert.equal(h.fetched.length, 0);
  });
}

test("worker does not submit inference after navigation during image fetch", async () => {
  const h = workerHarness();
  h.beforeBlob = () => { h.tab.url += "/next"; };
  assert.equal((await h.send()).ok, false);
  assert.equal(h.fetched.length, 1, "old context must not reach the API");
});

test("worker reuses persisted translations and corrections after service-worker restart", async () => {
  const first = workerHarness();
  const initial = await first.send();
  assert.equal(initial.data.cache_hit, false);
  assert.equal((await first.send({type: "MANGA_READER_SAVE_EDIT", key: initial.data.cache_key, epoch: initial.data.cache_epoch, index: 0, text: "แก้ถาวร"})).ok, true);
  const reopened = workerHarness({storage: first.storage});
  const reused = await reopened.send();
  assert.equal(reused.data.cache_hit, true);
  assert.equal(reused.data.regions[0].translated_text, "แก้ถาวร");
  assert.equal(reopened.fetched.filter(url => url.endsWith("/translate")).length, 0);
  assert.equal(reopened.fetched.filter(url => url.startsWith("https:")).length, 1, "image is revalidated");
});

for (const change of ["image", "profile", "context", "chapter"]) {
  test(`worker invalidates saved data when ${change} changes`, async () => {
    const h = workerHarness(), original = await h.send();
    if (change === "image") h.imageBytes += "changed";
    if (change === "profile") h.profile = "2".repeat(64);
    if (change === "context") h.message.context = "changed previous dialogue";
    if (change === "chapter") { h.message.pageUrl += "/next"; h.tab.url = h.message.pageUrl; }
    const updated = await h.send();
    assert.equal(updated.ok, true);
    assert.equal(updated.data.cache_hit, false);
    assert.notEqual(updated.data.cache_key, original.data.cache_key);
    assert.equal(h.fetched.filter(url => url.endsWith("/translate")).length, 2);
  });
}

test("worker shows a persistence warning when storage fails without losing translation", async () => {
  const h = workerHarness();
  h.failStorage = true;
  const response = await h.send();
  assert.equal(response.ok, true);
  assert.equal(response.data.cache_key, null);
  assert(response.data.cache_warning);
  assert.equal(response.data.regions[0].translated_text, "สวัสดี");
});

test("content scripts cannot read, edit or clear persistent Reader results", async () => {
  const h = workerHarness(), sender = {id: "test-extension", url: h.tab.url, tab: h.tab};
  for (const message of [h.message, {type: "MANGA_READER_CLEAR_CACHE"},
    {type: "MANGA_READER_SAVE_EDIT", key: "a".repeat(64), index: 0, text: "แก้"}]) {
    assert.equal((await h.send(message, sender)).ok, false);
  }
  assert.equal(h.fetched.length, 0);
});

test("reopening the panel restores a correction without another inference", async () => {
  const worker = workerHarness(), first = harness();
  first.state.translate = message => worker.send(message);
  first.state.mutate = message => worker.send(message);
  await first.scan();
  await descendants(first.elements.items).find(el => el.tagName === "button" && el.textContent === "แก้คำแปล").click();
  first.elements.items.querySelector("textarea").value = "คำแก้ที่อยู่ข้ามครั้ง";
  await descendants(first.elements.items).find(el => el.tagName === "button" && el.textContent === "บันทึก").click();
  const restarted = workerHarness({storage: worker.storage}), second = harness();
  second.state.translate = message => restarted.send(message);
  await second.scan();
  assert.match(second.text(), /คำแก้ที่อยู่ข้ามครั้ง/);
  assert.match(second.text(), /บันทึกไว้/);
  assert.equal(restarted.fetched.filter(url => url.endsWith("/translate")).length, 0);
});

test("a failed durable edit keeps the editor open and does not display it as saved", async () => {
  const h = harness();
  await h.scan();
  await descendants(h.elements.items).find(el => el.tagName === "button" && el.textContent === "แก้คำแปล").click();
  h.elements.items.querySelector("textarea").value = "ยังไม่ได้บันทึก";
  h.state.mutate = async () => ({ok: false, error: "Storage full"});
  await descendants(h.elements.items).find(el => el.tagName === "button" && el.textContent === "บันทึก").click();
  assert(h.elements.items.querySelector("textarea"));
  assert.match(h.text(), /สวัสดี/);
  assert.match(h.elements.status.textContent, /Storage full/);
});

test("clear during inference discards late results and prevents cache resurrection", {timeout: 5000}, async () => {
  const worker = workerHarness(), h = harness(), pending = deferred(), entered = deferred();
  worker.inference = () => { entered.resolve(); return pending.promise; };
  h.state.translate = message => worker.send(message);
  h.state.mutate = message => worker.send(message);
  const run = h.scan();
  // Native image hashing can outlive any fixed count of event-loop turns.
  await entered.promise;
  assert.equal(worker.fetched.filter(url => url.endsWith("/translate")).length, 1);
  await h.elements["clear-cache"].click();
  pending.resolve({ok: true, json: async () => ({profile: worker.profile, regions: reply().data.regions})});
  await run;
  assert.equal(h.text(), "");
  assert.deepEqual(worker.storage.mangaReaderCacheV1.entries, []);
});

test("clearing in another panel invalidates this panel's pending result", async () => {
  const h = harness(), pending = deferred();
  h.state.translate = () => pending.promise;
  const run = h.scan();
  await settle();
  await h.chrome.storage.onChanged.emit({mangaReaderCacheV1: {oldValue: {epoch: "old"}, newValue: {epoch: "new"}}}, "local");
  pending.resolve(reply());
  await run;
  assert.equal(h.text(), "");
});

test("scan preserves an unsaved editor until the reader saves or cancels", async () => {
  const h = harness();
  await h.scan();
  await descendants(h.elements.items).find(el => el.tagName === "button" && el.textContent === "แก้คำแปล").click();
  h.elements.items.querySelector("textarea").value = "ยังแก้ไม่เสร็จ";
  await h.scan();
  assert.equal(h.state.calls.length, 1);
  assert.equal(h.elements.items.querySelector("textarea").value, "ยังแก้ไม่เสร็จ");
  await descendants(h.elements.items).find(el => el.tagName === "button" && el.textContent === "ยกเลิก").click();
  await h.scan();
  assert.equal(h.state.calls.length, 2);
});

test("worker persists empty results without repeated inference", async () => {
  const worker = workerHarness();
  worker.inference = async () => ({ok: true, json: async () => ({profile: worker.profile, regions: []})});
  assert.equal((await worker.send()).data.regions.length, 0);
  assert.equal((await worker.send()).data.cache_hit, true);
  assert.equal(worker.fetched.filter(url => url.endsWith("/translate")).length, 1);
});

test("a revoked pairing cannot reuse cached dialogue through a failed profile check", async () => {
  const worker = workerHarness();
  assert.equal((await worker.send()).ok, true);
  worker.profileResponse = {ok: false, status: 401};
  assert.equal((await worker.send()).ok, false);
  assert.equal(worker.fetched.filter(url => url.endsWith("/translate")).length, 1);
});

test("reading controls change appearance without requesting translation", async () => {
  const h = harness();
  await h.elements["show-source"].click();
  await h.elements.theme.click();
  await h.elements["font-larger"].click();
  assert.equal(h.root.dataset.source, "visible");
  assert.equal(h.root.dataset.theme, "dark");
  assert.equal(h.root.style["--reader-font-size"], "20px");
  assert.equal(h.elements["show-source"].getAttribute("aria-pressed"), "true");
  assert.equal(h.state.calls.length, 0);
  assert.equal(h.state.savedAppearance.fontSize, 20);
});

test("font controls respect bounds and stored appearance is restored", async () => {
  const h = harness({savedAppearance: {theme: "dark", fontSize: 25, showSource: true}});
  await settle();
  assert.equal(h.root.dataset.theme, "dark");
  assert.equal(h.root.dataset.source, "visible");
  assert.equal(h.elements["font-larger"].disabled, true);
  for (let i = 0; i < 15; i++) await h.elements["font-smaller"].click();
  assert.equal(h.root.style["--reader-font-size"], "16px");
  assert.equal(h.elements["font-smaller"].disabled, true);
});

test("invalid saved appearance values cannot break reading layout", async () => {
  const h = harness({savedAppearance: {theme: "unknown", fontSize: 900, showSource: "yes"}});
  await settle();
  assert.equal(h.root.dataset.theme, "light");
  assert.equal(h.root.dataset.source, "hidden");
  assert.equal(h.root.style["--reader-font-size"], "19px");
});

test("empty state and dialogue count follow results and reset", async () => {
  const h = harness();
  assert.equal(h.elements["empty-state"].hidden, false);
  assert.equal(h.elements.items.hidden, true);
  await h.scan();
  assert.equal(h.elements["empty-state"].hidden, true);
  assert.equal(h.elements["reading-count"].textContent, "1 บทสนทนา");
  assert.equal(h.elements["source-label"].textContent, "reader.example");
  assert.equal(h.elements.scan.getAttribute("aria-busy"), "false");
  await h.reset();
  assert.equal(h.elements["empty-state"].hidden, false);
  assert.equal(h.elements.items.hidden, true);
});

test("reset from the menu closes it without deleting saved dialogue", async () => {
  const h = harness();
  h.elements["reader-menu"].open = true;
  let mutations = 0;
  h.state.mutate = async () => { mutations++; return {ok: true}; };
  await h.reset();
  assert.equal(h.elements["reader-menu"].open, false);
  assert.equal(mutations, 0);
});

test("Reader automatically loads account choices without inference or an extra click", async () => {
  const h = harness({modelAccess: true}); await settle();
  assert.equal(h.elements["model-current"].textContent, "Vision A");
  assert.equal(h.state.modelCalls.length, 2);
  assert.equal(h.elements["model-count"].textContent, "2 รุ่น");
  await h.openModels();
  assert.equal(h.state.modelCalls.length, 2, "opening uses the freshly loaded account catalog");
  assert.equal(h.elements["model-current"].textContent, "Vision A");
  assert.equal(h.elements["model-select"].disabled, false);
  assert.equal(h.elements["model-select"].value, "vision-a");
  assert.equal(h.state.calls.length, 0, "model metadata never submits inference");
});

test("switching models preserves dialogue and unsaved edits without inference", async () => {
  const h = harness({modelAccess: true}); await settle(); await h.scan();
  await descendants(h.elements.items).find(el => el.textContent === "แก้คำแปล").click();
  const editor = h.elements.items.querySelector("textarea"); editor.value = "คำแก้ไขที่ยังไม่บันทึก";
  await h.openModels(); await h.chooseModel("vision-b");
  assert.equal(h.elements["model-current"].textContent, "Vision B");
  assert.equal(h.state.model, "vision-b");
  assert.equal(h.state.calls.length, 1);
  assert.equal(h.elements.items.querySelector("textarea"), editor);
  assert.equal(editor.value, "คำแก้ไขที่ยังไม่บันทึก");
  assert.match(h.text(), /สวัสดี/);
  assert.match(h.elements["model-status"].textContent, /บันทึกโมเดลแล้ว/);
  const reopened = harness({modelAccess: true}); reopened.state.model = h.state.model; await settle();
  assert.equal(reopened.elements["model-current"].textContent, "Vision B");
});

test("switching a model affects only the next user-initiated translation", async () => {
  const h = harness({modelAccess: true}); await settle();
  const used = [];
  h.state.translate = async () => { used.push(h.state.model); return reply(); };
  await h.scan(); await h.openModels(); await h.chooseModel("vision-b");
  assert.deepEqual(used, ["vision-a"]);
  await h.scan();
  assert.deepEqual(used, ["vision-a", "vision-b"]);
});

test("model selection is locked for the full translation queue", async () => {
  const h = harness({modelAccess: true}), pending = deferred(); await settle(); await h.openModels();
  h.state.translate = () => pending.promise;
  const run = h.scan(); await settle();
  assert.equal(h.elements["model-select"].disabled, true);
  await h.chooseModel("vision-b");
  assert(!h.state.modelCalls.some(call => call.path.endsWith("/model")));
  assert.match(h.elements["model-status"].textContent, /รอแปล/);
  pending.resolve(reply()); await run;
  assert.equal(h.elements["model-select"].disabled, false);
});

test("a pending model save blocks scan and retries even after Reader reset", async () => {
  const h = harness({modelAccess: true}), pending = deferred(); await settle(); await h.openModels();
  h.state.modelRequest = path => path.endsWith("/model") ? pending.promise : undefined;
  const change = h.chooseModel("vision-b"); await settle();
  assert.equal(h.elements.scan.disabled, true);
  assert.equal(h.elements.grant.disabled, true);
  assert.equal(h.elements["clear-cache"].disabled, true);
  await h.scan(); await h.reset();
  assert.equal(h.elements.scan.disabled, true);
  assert.equal(h.state.calls.length, 0);
  pending.resolve({ok: true, status: 200, json: async () => ({model: "vision-b", version: "b".repeat(64)})});
  await change;
  assert.equal(h.elements.scan.disabled, false);
  assert.equal(h.elements["model-current"].textContent, "Vision B");
});

test("model catalog failure preserves the reading session and offers manual reload", async () => {
  const h = harness({modelAccess: true}); await settle(); await h.scan();
  h.state.modelRequest = path => path.endsWith("/models") ? {ok: false, status: 502} : undefined;
  await h.openModels();
  await h.elements["model-reload"].click();
  assert.match(h.elements["model-status"].textContent, /โหลดรายการไม่สำเร็จ/);
  assert.match(h.text(), /สวัสดี/);
  assert.equal(h.elements["model-select"].disabled, true);
  h.state.modelRequest = null; await h.elements["model-reload"].click();
  assert.equal(h.elements["model-select"].disabled, false);
});

for (const code of [409, 502]) test("model save failure " + code + " never claims a new selected model", async () => {
  const h = harness({modelAccess: true}); await settle(); await h.openModels();
  h.state.modelRequest = path => path.endsWith("/model") ? {ok: false, status: code} : undefined;
  await h.chooseModel("vision-b");
  assert.equal(h.state.model, "vision-a");
  assert.equal(h.elements["model-current"].textContent, "ตรวจโมเดลอีกครั้ง");
  assert.equal(h.elements["model-select"].value, "vision-a");
  assert.equal(h.elements["model-select"].disabled, true);
  assert.doesNotMatch(h.elements["model-status"].textContent, /บันทึกโมเดลแล้ว/);
});

test("legacy pairing shows the model but requires explicit management pairing to change it", async () => {
  const h = harness({modelAccess: true}); delete h.state.credentials.mangaSettingsCapability; await settle();
  await h.openModels();
  assert.equal(h.elements["model-current"].textContent, "vision-a");
  assert.equal(h.elements["model-settings"].hidden, false);
  assert.equal(h.elements["model-select"].disabled, true);
  assert(!h.state.modelCalls.some(call => call.path.includes("/settings/")));
});

test("credential changes discard a late model save and disable old authority", async () => {
  const h = harness({modelAccess: true}), pending = deferred(); await settle(); await h.openModels();
  h.state.modelRequest = path => path.endsWith("/model") ? pending.promise : undefined;
  const change = h.chooseModel("vision-b"); await settle();
  h.state.credentials = {};
  await h.chrome.storage.onChanged.emit({mangaSettingsCapability: {}}, "local");
  pending.resolve({ok: true, status: 200, json: async () => ({model: "vision-b", version: "b".repeat(64)})});
  await change; await settle();
  assert.equal(h.elements["model-current"].textContent, "ยังไม่ได้เลือก");
  assert.equal(h.elements["model-select"].disabled, true);
  assert.equal(h.elements.scan.disabled, false);
  assert.doesNotMatch(h.elements["model-status"].textContent, /บันทึกโมเดลแล้ว/);
});

test("a model changed from elsewhere stops the queue without submitting remaining images", async () => {
  const h = harness();
  h.state.images.push({index: 1, url: "https://reader.example/2.png"}, {index: 2, url: "https://reader.example/3.png"});
  h.state.translate = async message => {
    if (message.url.endsWith("1.png")) return {ok: true, data: {...reply().data, profile: "1".repeat(64)}};
    assert.equal(message.profile, "1".repeat(64));
    return {ok: false, settingsChanged: true, error: "Settings changed"};
  };
  await h.scan();
  assert.equal(h.state.calls.length, 2);
  assert.match(h.text(), /สวัสดี/);
  assert.match(h.text(), /ยังไม่ได้ส่งแปล/);
  assert.match(h.elements.status.textContent, /หยุดคิว/);
  assert.equal(h.elements.scan.disabled, false);
});

test("worker exposes the validated profile and refuses a changed model before inference or cache reuse", async () => {
  const worker = workerHarness();
  const original = await worker.send();
  assert.equal(original.data.profile, worker.profile);
  const reused = await worker.send();
  assert.equal(reused.data.cache_hit, true);
  assert.equal(reused.data.profile, worker.profile);
  worker.message.profile = worker.profile;
  worker.profile = "2".repeat(64);
  const changed = await worker.send();
  assert.equal(changed.ok, false);
  assert.equal(changed.settingsChanged, true);
  assert.equal(worker.fetched.filter(url => url.endsWith("/translate")).length, 1);
});

test("opening the picker during the initial status request still loads its catalog afterwards", async () => {
  const h = harness({modelAccess: true}), pending = deferred();
  h.state.modelRequest = path => path === "/api/v1/provider/status" ? pending.promise : undefined;
  await h.openModels();
  assert.equal(h.elements["model-select"].disabled, true);
  pending.resolve({ok: true, status: 200, json: async () => ({connected: true, plan_usage_enabled: true, model: "vision-a"})});
  await settle();
  assert.equal(h.elements["model-select"].disabled, false);
  assert(h.state.modelCalls.some(call => call.path.endsWith("/models")));
});

test("a provider-side settings conflict stops the Reader before its next queued inference", async () => {
  const worker = workerHarness(), h = harness();
  worker.inference = () => ({ok: false, status: 409, text: async () => 'Reader settings changed during translation'});
  h.state.images.push({index: 1, url: "https://reader.example/2.png"}, {index: 2, url: "https://reader.example/3.png"});
  h.chrome.runtime.sendMessage = message => worker.send(message);
  await h.scan();
  assert.equal(worker.fetched.filter(url => url.endsWith("/translate")).length, 1);
  assert.match(h.text(), /ยังไม่ได้ส่งแปล/);
  assert.match(h.elements.status.textContent, /หยุดคิว/);
});

test("all eight account choices load automatically in provider order and remain selectable", async () => {
  const h = harness({modelAccess: true});
  h.state.catalog = Array.from({length: 8}, (_, i) => ({slug: i ? "generated-model-" + i : "vision-a", display_name: "Account choice " + i}));
  await settle();
  assert.equal(h.elements["model-select"].children.length, 8);
  assert.equal(h.elements["model-count"].textContent, "8 รุ่น");
  assert.equal(h.elements["model-count"].hidden, false);
  assert.deepEqual(h.elements["model-select"].children.map(option => option.value), h.state.catalog.map(model => model.slug));
  assert.match(h.elements["model-status"].textContent, /พบ 8 โมเดลจากบัญชีนี้/);
  await h.chooseModel("generated-model-7");
  assert.equal(h.state.model, "generated-model-7");
  assert.equal(h.state.calls.length, 0);
});

test("switching account metadata replaces the choices and count without changing the selected model", async () => {
  const h = harness({modelAccess: true}); await settle();
  h.state.catalog = [{slug: "account-b-choice", display_name: "Account B choice"}];
  h.state.model = "account-b-choice";
  await h.state.windowEvents.focus.emit(); await settle();
  assert.equal(h.elements["model-select"].children.length, 1);
  assert.equal(h.elements["model-select"].value, "account-b-choice");
  assert.equal(h.elements["model-count"].textContent, "1 รุ่น");
  assert(!h.state.modelCalls.some(call => call.path.endsWith("/model")));
});

test("automatic catalog failure leaves dialogue usable and allows an explicit reload", async () => {
  const h = harness({modelAccess: true});
  h.state.modelRequest = path => path.endsWith("/models") ? {ok: false, status: 502} : undefined;
  await settle();
  assert.equal(h.elements["model-count"].hidden, true);
  assert.equal(h.elements["model-select"].disabled, true);
  assert.equal(h.elements.scan.disabled, false);
  assert.match(h.elements["model-status"].textContent, /โหลดรายการไม่สำเร็จ/);
  h.state.modelRequest = null;
  await h.elements["model-reload"].click();
  assert.equal(h.elements["model-select"].children.length, 2);
  assert.equal(h.elements["model-count"].textContent, "2 รุ่น");
});

test("a disconnected account offers connection setup without automatically querying its catalog", async () => {
  const h = harness({modelAccess: true});
  h.state.modelRequest = path => path.endsWith("/provider/status") ? {ok: true, status: 200, json: async () => ({connected: false, plan_usage_enabled: false, model: null})} : undefined;
  await settle();
  assert.equal(h.state.modelCalls.length, 1);
  assert.match(h.elements["model-status"].textContent, /เชื่อมต่อและอนุญาต/);
  assert.equal(h.elements["model-settings"].hidden, false);
  assert.equal(h.elements["model-count"].hidden, true);
});
