/* App-owned recovery text. Never display raw provider/API response bodies. */
const CONNECTION_ERRORS = {
  reconnect_required: ["การเชื่อมต่อ ChatGPT หมดอายุ เปิด Settings เพื่อเชื่อมต่อบัญชีเดิมอีกครั้ง", "settings", true],
  permission_required: ["บัญชีหรือคำขอนี้ยังไม่ได้รับอนุญาต เปิด Settings เพื่อตรวจสิทธิ์", "settings", true],
  usage_limit: ["ถึงขีดจำกัดการใช้งานแล้ว ตรวจการใช้งานบัญชีและลองใหม่ภายหลัง", "usage", true],
  unsupported_capability: ["โมเดลหรือคำขอนี้ไม่รองรับการทำงานที่ขอ เปิด Settings เพื่อตรวจโมเดล", "settings", true],
  provider_unavailable: ["ผู้ให้บริการหรือเครือข่ายยังไม่พร้อม กรุณาลองใหม่ภายหลัง", "retry", false],
  account_changed: ["บัญชีหรือการตั้งค่าเปลี่ยนแล้ว กรุณาตรวจสถานะและเริ่มใหม่", "settings", true],
  pairing_required: ["สิทธิ์ส่วนขยายใช้ไม่ได้ เปิด Settings เพื่อตรวจการจับคู่", "settings", true],
  local_budget: ["ถึงขีดจำกัดการแปลในเครื่องแล้ว รอสักครู่ก่อนลองใหม่", "retry", true],
  invalid_response: ["ระบบแปลตอบกลับไม่สำเร็จ กรุณาลองใหม่", "retry", false]
};

async function connectionFailure(response) {
  let detail;
  try { detail = (await response.json()).detail; } catch { /* Older APIs may return text. */ }
  const code = detail && typeof detail === "object" && Object.hasOwn(CONNECTION_ERRORS, detail.code) ? detail.code
    : response.status === 409 ? "account_changed" : [401, 403].includes(response.status) ? "pairing_required"
      : response.status === 429 ? "local_budget" : response.status === 503 ? "provider_unavailable" : "invalid_response";
  const [message, action, stopQueue] = CONNECTION_ERRORS[code];
  return Object.assign(new Error(message), {code, action, stopQueue, settingsChanged: response.status === 409});
}
