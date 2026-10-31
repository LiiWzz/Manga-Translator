const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function source({allowed = true, response} = {}) {
  const calls = [], permissions = [];
  const image = vm.runInNewContext(fs.readFileSync("apps/extension/reader-image-source.js", "utf8") + "; ReaderImageSource", {
    URL, Blob, Uint8Array, atob, AbortSignal,
    chrome: {permissions: {contains: async options => { permissions.push(options.origins); return allowed; }}},
    fetch: async (url, options) => { calls.push({url, options}); return response || new Response("generated image bytes", {headers: {"content-type": "image/png"}}); }
  });
  return {image, calls, permissions};
}
const page = "https://reader.example/chapter";
const cdn = "https://new-cdn.example/1.png";

test("any HTTPS image origin works after per-origin approval without sending cookies or following redirects", async () => {
  const h = source();
  const blob = await h.image.fetch(cdn, page);
  assert.equal(await blob.text(), "generated image bytes");
  assert.equal(blob.type, "image/png");
  assert.equal(h.permissions[0][0], "https://new-cdn.example/*");
  assert.equal(h.calls[0].options.credentials, "omit");
  assert.equal(h.calls[0].options.redirect, "error");
  assert.equal(h.calls[0].options.cache, "no-store");
  assert(h.calls[0].options.signal instanceof AbortSignal);
});

test("unapproved image origins return an exact permission request without touching the network", async () => {
  const h = source({allowed: false});
  await assert.rejects(h.image.fetch(cdn, page), error => error.permissionOrigin === "https://new-cdn.example/*");
  assert.equal(h.calls.length, 0);
});

test("invalid, embedded-credential and insecure cross-origin URLs cannot request permissions or fetch", async () => {
  const h = source();
  for (const url of ["file:///image.png", "data:image/png;base64,YQ==", "blob:https://reader.example/id", "ftp://cdn.example/1.png",
    "https://user:password@cdn.example/image.png", "http://cdn.example/1.png"]) {
    await assert.rejects(h.image.fetch(url, page));
  }
  await assert.rejects(h.image.fetch(cdn, "chrome://settings/"));
  assert.equal(h.permissions.length, 0);
  assert.equal(h.calls.length, 0);
  assert.equal(h.image.origin("http://reader.example/1.png", "http://reader.example/chapter"), "http://reader.example/*");
});

for (const status of [401, 403, 429]) test("HTTP " + status + " remains an error without fallback requests", async () => {
  const h = source({response: new Response("denied", {status})});
  await assert.rejects(h.image.fetch(cdn, page), new RegExp("HTTP " + status));
  assert.equal(h.calls.length, 1);
});

test("HTML and unsupported image formats never reach translation", async () => {
  for (const mime of ["text/html", "image/svg+xml", "image/gif"]) {
    const h = source({response: new Response("not an eligible image", {headers: {"content-type": mime}})});
    await assert.rejects(h.image.fetch(cdn, page), /ชนิดภาพ/);
  }
});

test("an oversized response is stopped both with Content-Length and during streaming", async () => {
  const announced = source({response: new Response("small", {headers: {"content-type": "image/png", "content-length": "8388609"}})});
  await assert.rejects(announced.image.fetch(cdn, page), /8 MB/);
  let cancelled = false;
  const streamed = source({response: new Response(new ReadableStream({
    pull(controller) { controller.enqueue(new Uint8Array(1024 * 1024)); },
    cancel() { cancelled = true; }
  }), {headers: {"content-type": "image/png"}})});
  await assert.rejects(streamed.image.fetch(cdn, page), /8 MB/);
  assert.equal(cancelled, true);
});

test("confirmed crops accept only bounded base64 PNG, JPEG or WebP bytes", async () => {
  const h = source();
  for (const mime of ["image/png", "image/jpeg", "image/webp"]) {
    const blob = h.image.fromDataUrl("data:" + mime + ";base64,Z2VuZXJhdGVk");
    assert.equal(await blob.text(), "generated");
    assert.equal(blob.type, mime);
  }
  for (const value of [null, "https://cdn.example/1.png", "data:image/svg+xml;base64,YQ==", "data:image/png;base64,",
    "data:image/png;base64,YQ=", "data:image/png;base64,@@@@", "data:image/png;base64," + "A".repeat(11184900)]) {
    assert.throws(() => h.image.fromDataUrl(value));
  }
  assert.equal(h.calls.length, 0);
});
