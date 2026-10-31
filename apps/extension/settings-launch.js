"use strict";
let opening = false;
async function openSettings() {
  if (opening) return;
  opening = true;
  const status = document.getElementById("launch-status");
  document.getElementById("retry").hidden = true;
  status.textContent = "กำลังเปิด Settings ที่อนุญาตไว้…";
  let form;
  try {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    const {mangaSettingsCapability} = await chrome.storage.local.get("mangaSettingsCapability");
    if (!mangaSettingsCapability) {
      status.textContent = "ยังไม่มีสิทธิ์จัดการ Settings กลับไปจับคู่ในส่วนขยายก่อน"; return;
    }
    const response = await fetch("http://127.0.0.1:8000/api/v1/settings/ticket", {
      method: "POST", cache: "no-store", credentials: "omit", redirect: "error",
      signal: AbortSignal.timeout(5000), headers: {Authorization: "Bearer " + mangaSettingsCapability}});
    if (response.status === 401 || response.status === 403) {
      status.textContent = "สิทธิ์จัดการ Settings ถูกยกเลิกแล้ว กลับไปจับคู่ใหม่ในส่วนขยาย"; return;
    }
    if (!response.ok) throw new Error("ticket");
    const {ticket} = await response.json();
    if (typeof ticket !== "string" || ticket.length < 32 || ticket.length > 128) throw new Error("ticket");
    // Dedicated-tab POST keeps bearer credentials and tickets out of URLs.
    form = document.createElement("form");
    form.method = "post";
    form.action = "http://127.0.0.1:8000/auth/extension-session";
    const input = document.createElement("input");
    input.type = "hidden"; input.name = "ticket"; input.value = ticket;
    form.append(input); document.body.append(form);
    form.submit();
  } catch {
    if (form) form.remove();
    status.textContent = "เปิด Settings ไม่สำเร็จ ตรวจว่าระบบแปลกำลังทำงาน แล้วลองอีกครั้ง";
    document.getElementById("retry").hidden = false;
  } finally {
    opening = false;
  }
}
// Clean the one-use ticket after navigation starts, without cancelling submit.
window.addEventListener("pagehide", () => document.querySelector("form")?.remove());
document.getElementById("retry").addEventListener("click", openSettings);
document.getElementById("back").addEventListener("click", () => chrome.runtime.openOptionsPage());
openSettings();
