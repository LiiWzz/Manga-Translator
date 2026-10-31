const status = document.getElementById("status");
document.getElementById("connect").addEventListener("click", () => {
  chrome.tabs.create({url: "http://127.0.0.1:8000/settings"});
});
document.getElementById("pair").addEventListener("click", async () => {
  const code = document.getElementById("pair-code").value.trim();
  try {
    const response = await fetch("http://127.0.0.1:8000/api/v1/pair/redeem", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({code})});
    if (!response.ok) throw new Error("Pairing rejected: HTTP " + response.status);
    const {token} = await response.json();
    await chrome.storage.local.set({mangaCapability:token});
    document.getElementById("pair-code").value = "";
    status.textContent = "Extension paired. You can check ChatGPT status.";
  } catch (error) {status.textContent = error.message;}
});
document.getElementById("unpair").addEventListener("click", async () => {
  await chrome.storage.local.remove("mangaCapability");
  status.textContent = "Local capability forgotten. Revoke it from authenticated Settings as well.";
});
async function check() {
  try {
    const {mangaCapability} = await chrome.storage.local.get("mangaCapability");
    if (!mangaCapability) {status.textContent="Not paired. Generate code in unlocked Settings."; return;}
    const response = await fetch("http://127.0.0.1:8000/api/v1/provider/status", {headers:{Authorization:"Bearer " + mangaCapability}});
    if (!response.ok) throw new Error("HTTP " + response.status);
    const result = await response.json();
    status.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    status.textContent = "Backend offline or not accessible: " + error.message;
  }
}
document.getElementById("check").addEventListener("click", check);
check();

chrome.storage.local.get("mangaDebug").then(({mangaDebug}) => {
  document.getElementById("debug").checked = Boolean(mangaDebug);
});
document.getElementById("debug").addEventListener("change", event => {
  chrome.storage.local.set({mangaDebug: event.target.checked});
});
