// Regression contract for Chrome-managed toolbar Side Panel opening.
// Unlike node --check this also checks wiring, to prevent an await before panel.open().
const fs = require("node:fs");
const assert = require("node:assert/strict");
const bg=fs.readFileSync("apps/extension/background.js","utf8");
const panel=fs.readFileSync("apps/extension/reader-panel.js","utf8");
const panelHtml=fs.readFileSync("apps/extension/reader-panel.html","utf8");
assert(panelHtml.indexOf('src="reader-models.js"') >= 0);
assert(panelHtml.indexOf('src="reader-models.js"') < panelHtml.indexOf('src="reader-panel.js"'));
const manifest=JSON.parse(fs.readFileSync("apps/extension/manifest.json","utf8"));
assert.equal(manifest.side_panel.default_path,"reader-panel.html");
assert(manifest.permissions.includes("sidePanel"));
assert(bg.includes("setPanelBehavior({openPanelOnActionClick: true})"));
assert(!bg.includes("chrome.action.onClicked"),"toolbar must use Chrome-managed behavior");
assert(panel.includes("chrome.scripting.executeScript("));
assert(panel.includes('files: ["reader-content.js"]'));
assert(panel.includes('type: "MANGA_READER_DISCOVER"'));
assert(panel.includes("chrome.permissions.request({origins: [request.pattern]})"));
assert(manifest.permissions.includes("tabs"));
assert(manifest.optional_host_permissions.includes("https://*/*"));
console.log("Side Panel action wiring regression passed.");

// Keep Reader behavior regressions in the existing CI entrypoint as well.
require("./test-reader-reliability.cjs");
require("./test-reader-cache.cjs");
require("./test-settings.cjs");
for (const file of ["connection-errors.js", "reader-cache.js", "background.js", "reader-models.js", "reader-panel.js", "options.js", "settings-launch.js"]) {
  new (require("node:vm").Script)(fs.readFileSync("apps/extension/" + file, "utf8"), {filename: file});
}
