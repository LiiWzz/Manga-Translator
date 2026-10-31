const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ReaderCache} = require("./reader-cache.js");

function storage() {
  const values = {mangaCapability: "test-only-capability", mangaDebug: true};
  return {values,
    async get(key) { return structuredClone({[key]: values[key]}); },
    async set(data) { Object.assign(values, structuredClone(data)); }
  };
}
const key = letter => letter.repeat(64);
const result = text => ({regions: [{source_text: "HELLO", translated_text: text || "สวัสดี"}]});

test("results and separate user corrections survive a fresh cache instance", async () => {
  const local = storage(), first = new ReaderCache(local), epoch = await first.begin();
  await first.put(key("a"), result(), epoch);
  await first.edit(key("a"), 0, "คำแก้ไข", epoch);
  const reopened = new ReaderCache(local);
  assert.equal((await reopened.get(key("a"), await reopened.begin())).regions[0].translated_text, "คำแก้ไข");
  const entry = local.values[ReaderCache.storageKey].entries[0];
  assert.equal(entry.data.regions[0].translated_text, "สวัสดี");
  assert.equal(entry.edits[0], "คำแก้ไข");
});

test("cache whitelists dialogue fields and never copies credentials, image bytes or URLs", async () => {
  const local = storage(), cache = new ReaderCache(local), epoch = await cache.begin();
  await cache.put(key("a"), {...result(), token: "not-a-real-token", url: "https://private.example/", image: "data:image/png;base64,test"}, epoch);
  const raw = JSON.stringify(local.values[ReaderCache.storageKey]);
  assert.doesNotMatch(raw, /not-a-real-token|private.example|data:image|test-only-capability/);
});

test("model provenance survives cache restart and edits without moving between models", async () => {
  const local = storage(), cache = new ReaderCache(local), epoch = await cache.begin();
  await cache.put(key("a"), {...result(), model: "generated-model-a", email: "private@example.invalid"}, epoch);
  await cache.put(key("b"), {...result(), model: "generated-model-b"}, epoch);
  await cache.edit(key("a"), 0, "คำแก้ไข", epoch);
  const reopened = new ReaderCache(local), current = await reopened.begin();
  assert.equal((await reopened.get(key("a"), current)).model, "generated-model-a");
  assert.equal((await reopened.get(key("b"), current)).model, "generated-model-b");
  assert.equal((await reopened.get(key("a"), current)).regions[0].translated_text, "คำแก้ไข");
  assert.doesNotMatch(JSON.stringify(local.values[ReaderCache.storageKey]), /private@example/);
});

test("legacy cache results remain readable with unknown model provenance", async () => {
  const local = storage(), cache = new ReaderCache(local), epoch = await cache.begin();
  await cache.put(key("a"), result(), epoch);
  delete local.values[ReaderCache.storageKey].entries[0].data.model;
  const reopened = new ReaderCache(local);
  const value = await reopened.get(key("a"), await reopened.begin());
  assert.equal(value.model, null);
  assert.equal(value.regions[0].translated_text, "สวัสดี");
});

test("absolute expiry removes original dialogue and edits even after recent access", async () => {
  let time = 0;
  const local = storage(), cache = new ReaderCache(local, {now: () => time, ttl: 100});
  const epoch = await cache.begin();
  await cache.put(key("a"), result(), epoch);
  await cache.edit(key("a"), 0, "แก้", epoch);
  time = 90;
  assert(await cache.get(key("a"), epoch));
  time = 100;
  assert.equal(await cache.get(key("a"), epoch), null);
  assert.deepEqual(local.values[ReaderCache.storageKey].entries, []);
});

test("entry bound evicts the least recently used result", async () => {
  let time = 0;
  const cache = new ReaderCache(storage(), {now: () => ++time, maxEntries: 2}), epoch = await cache.begin();
  await cache.put(key("a"), result(), epoch);
  await cache.put(key("b"), result(), epoch);
  await cache.get(key("a"), epoch);
  await cache.put(key("c"), result(), epoch);
  assert.equal(await cache.get(key("b"), epoch), null);
  assert(await cache.get(key("a"), epoch));
});

test("UTF-8 byte bound accounts for Thai text", async () => {
  const local = storage(), cache = new ReaderCache(local, {maxBytes: 600}), epoch = await cache.begin();
  await cache.put(key("a"), result("ก".repeat(100)), epoch);
  await cache.put(key("b"), result("ข".repeat(100)), epoch);
  assert(Buffer.byteLength(JSON.stringify(local.values[ReaderCache.storageKey])) <= 600);
});

test("clear removes only Reader data and rejects a pending write even after worker restart", async () => {
  const local = storage(), cache = new ReaderCache(local), old = await cache.begin();
  await cache.put(key("a"), result(), old);
  await cache.edit(key("a"), 0, "แก้", old);
  await cache.clear();
  const restarted = new ReaderCache(local);
  assert.equal(await restarted.put(key("b"), result(), old), false);
  assert.deepEqual(local.values[ReaderCache.storageKey].entries, []);
  assert.equal(local.values.mangaCapability, "test-only-capability");
  assert.equal(local.values.mangaDebug, true);
});

test("simultaneous writes retain both images", async () => {
  const cache = new ReaderCache(storage()), epoch = await cache.begin();
  await Promise.all([cache.put(key("a"), result(), epoch), cache.put(key("b"), result(), epoch)]);
  assert(await cache.get(key("a"), epoch));
  assert(await cache.get(key("b"), epoch));
});

test("a quota error is reported and does not poison later operations", async () => {
  const local = storage(), set = local.set, cache = new ReaderCache(local), epoch = await cache.begin();
  await cache.put(key("a"), result(), epoch);
  local.set = async () => { throw new Error("Quota exceeded"); };
  await assert.rejects(cache.edit(key("a"), 0, "แก้", epoch), /Quota/);
  local.set = set;
  assert.equal((await cache.get(key("a"), epoch)).regions[0].translated_text, "สวัสดี");
  await cache.edit(key("a"), 0, "แก้ได้แล้ว", epoch);
});

test("malformed and expired stored entries are pruned without touching pairing", async () => {
  const local = storage();
  local.values[ReaderCache.storageKey] = {version: 1, epoch: "old", credentials: "discard", entries: [
    {key: key("a"), created: Date.now(), used: Date.now(), data: {regions: [null]}},
    {key: key("b"), created: 0, used: 0, data: result()}
  ]};
  await new ReaderCache(local).begin();
  assert.deepEqual(local.values[ReaderCache.storageKey], {version: 1, epoch: "old", entries: []});
  assert.equal(local.values.mangaCapability, "test-only-capability");
});

test("edits reject missing rows and invalid text", async () => {
  const cache = new ReaderCache(storage()), epoch = await cache.begin();
  await cache.put(key("a"), result(), epoch);
  await assert.rejects(cache.edit(key("a"), 2, "แก้", epoch));
  await assert.rejects(cache.edit(key("a"), 0, " ", epoch));
  await assert.rejects(cache.edit(key("a"), 0, "ก".repeat(1001), epoch));
  await cache.clear();
  await assert.rejects(cache.edit(key("a"), 0, "แก้", epoch));
});

test("a concurrent translation of the same input cannot overwrite a saved correction", async () => {
  const cache = new ReaderCache(storage()), epoch = await cache.begin();
  await cache.put(key("a"), result(), epoch);
  await cache.edit(key("a"), 0, "คำแก้ไข", epoch);
  await cache.put(key("a"), result(), epoch);
  assert.equal((await cache.get(key("a"), epoch)).regions[0].translated_text, "คำแก้ไข");
});

test("an old edit cannot modify a fresh translation after clear", async () => {
  const cache = new ReaderCache(storage()), old = await cache.begin();
  await cache.put(key("a"), result(), old);
  await cache.clear();
  const fresh = await cache.begin();
  await cache.put(key("a"), result(), fresh);
  await assert.rejects(cache.edit(key("a"), 0, "คำแก้เก่า", old));
  assert.equal((await cache.get(key("a"), fresh)).regions[0].translated_text, "สวัสดี");
});
