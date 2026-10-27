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
  }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get textContent() { return this.ownText + this.children.map(el => el.textContent).join(" "); }
  append(...children) { children.forEach(el => { el.parent = this; this.children.push(el); }); }
  replaceChildren(...children) { this.ownText = ""; this.children = []; this.append(...children); }
  remove() { this.parent.children = this.parent.children.filter(el => el !== this); }
  focus() {}
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async click() {
    if (!this.disabled) await Promise.all((this.listeners.click || []).map(fn => fn()));
  }
  querySelector(tag) { return descendants(this).find(el => el.tagName === tag) || null; }
}
function descendants(el) { return el.children.flatMap(child => [child, ...descendants(child)]); }
function harness() {
  const elements = Object.fromEntries(["status", "items", "scan", "grant", "reset", "settings"].map(id => [id, new Element()]));
  const state = {
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
    runtime: {
      sendMessage: message => { state.calls.push(message); return state.translate(message); },
      openOptionsPage() {}
    }
  };
  vm.runInNewContext(fs.readFileSync("apps/extension/reader-panel.js", "utf8"), {
    chrome, URL, document: {getElementById: id => elements[id], createElement: tag => new Element(tag)}
  });
  return {
    state, chrome, elements,
    scan: () => elements.scan.click(),
    reset: () => elements.reset.click(),
    text: () => elements.items.textContent,
    retry: () => descendants(elements.items).find(el => el.tagName === "button" && el.textContent === "ลองใหม่")?.click()
  };
}
function reply(source = "HELLO", translated = "สวัสดี") {
  return {ok: true, data: {regions: [{source_text: source, translated_text: translated}]}};
}
async function settle() { for (let i = 0; i < 8; i++) await new Promise(setImmediate); }

test("failed image keeps its error and retries only on explicit request", async () => {
  const h = harness();
  h.state.images.push({index: 1, url: "https://reader.example/2.png"});
  h.state.translate = async message => message.url.endsWith("1.png") ? reply() : {ok: false, error: "Image HTTP 503"};
  await h.scan();
  assert.match(h.text(), /Image HTTP 503/);
  assert.match(h.text(), /สวัสดี/);
  await h.scan();
  assert.equal(h.state.calls.length, 2, "scan must not resubmit success or failure");
  h.state.translate = async () => reply("BYE", "ลาก่อน");
  await h.retry();
  assert.equal(h.state.calls.length, 3);
  assert.match(h.state.calls[2].url, /2.png$/);
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
  assert.equal(h.state.calls.length, 1);
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
  assert.equal(h.state.calls.length, 3, "discarded response must not enter cache");
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

function workerHarness() {
  let listener;
  const state = {
    tab: {id: 1, url: "https://reader.example/chapter/1", status: "complete"},
    active: true, fetched: [], beforeBlob: () => {},
    message: {type: "MANGA_READER_TRANSLATE", tabId: 1, pageUrl: "https://reader.example/chapter/1", url: "https://reader.example/1.png", context: "prior dialogue"}
  };
  vm.runInNewContext(fs.readFileSync("apps/extension/background.js", "utf8"), {
    URL, FormData, console,
    chrome: {
      sidePanel: {setPanelBehavior: async () => {}},
      runtime: {id: "test-extension", onMessage: {addListener(fn) { listener = fn; }}},
      storage: {local: {get: async () => ({mangaCapability: "test-only-local-capability"})}},
      tabs: {get: async () => ({...state.tab}), query: async () => state.active ? [{...state.tab}] : []}
    },
    fetch: async url => {
      state.fetched.push(url);
      if (url.startsWith("https:")) return {
        ok: true, headers: new Headers({"content-type": "image/png"}),
        blob: async () => { state.beforeBlob(); return new Blob(["generated-test-bytes"], {type: "image/png"}); }
      };
      return {ok: true, json: async () => ({regions: []})};
    }
  });
  state.send = () => new Promise(resolve => listener(state.message, {id: "test-extension"}, resolve));
  return state;
}

test("worker submits a reader request only for the active source page", async () => {
  const h = workerHarness();
  assert.equal((await h.send()).ok, true);
  assert.equal(h.fetched.length, 2);
  assert.match(h.fetched[1], /reader\/translate$/);
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
