/* Image bytes stay in extension memory; origins are approved one at a time. */
const ReaderImageSource = {
  maxBytes: 8 * 1024 * 1024,
  types: ["image/png", "image/jpeg", "image/webp"],

  origin(url, pageUrl) {
    const page = new URL(pageUrl), image = new URL(url);
    if (!/^https?:$/.test(page.protocol) || !/^https?:$/.test(image.protocol)
        || image.username || image.password || (image.protocol !== "https:" && image.origin !== page.origin)) {
      throw new Error("อ่าน URL ภาพนี้ไม่ได้ ลองใช้เลือกพื้นที่แปลสำหรับภาพที่คุณมีสิทธิ์อ่าน");
    }
    return image.origin + "/*";
  },

  async fetch(url, pageUrl) {
    const pattern = this.origin(url, pageUrl);
    if (!await chrome.permissions.contains({origins: [pattern]})) {
      throw Object.assign(new Error("ต้องอนุญาตโดเมนรูปภาพก่อน: " + new URL(url).hostname), {permissionOrigin: pattern});
    }
    let response;
    try {
      response = await fetch(url, {credentials: "omit", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(15000)});
    } catch {
      throw new Error("ดึงภาพไม่ได้หรือหมดเวลา เว็บไซต์อาจจำกัดการเข้าถึงภาพ");
    }
    if (!response.ok) throw new Error("Image HTTP " + response.status + ": เว็บไซต์ไม่อนุญาตหรือภาพไม่พร้อมใช้งาน");
    const mime = response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() || "";
    if (!this.types.includes(mime)) throw new Error("ชนิดภาพนี้ยังอ่านโดยตรงไม่ได้ ลองใช้เลือกพื้นที่แปล");
    if (Number(response.headers.get("content-length") || 0) > this.maxBytes) throw new Error("Image exceeds 8 MB limit");
    // Stop oversized streams before buffering the entire response.
    if (response.body?.getReader) {
      const reader = response.body.getReader(), chunks = [];
      let size = 0;
      try {
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > this.maxBytes) throw new Error("Image exceeds 8 MB limit");
          chunks.push(value);
        }
      } finally { await reader.cancel().catch(() => {}); }
      return new Blob(chunks, {type: mime});
    }
    const blob = await response.blob();
    if (blob.size > this.maxBytes) throw new Error("Image exceeds 8 MB limit");
    return blob;
  },

  fromDataUrl(value) {
    if (typeof value !== "string" || value.length > Math.ceil(this.maxBytes / 3) * 4 + 64) {
      throw new Error("พื้นที่ที่เลือกใหญ่เกิน 8 MB กรุณาเลือกพื้นที่เล็กลง");
    }
    const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$/.exec(value);
    if (!match || match[2].length % 4) throw new Error("ข้อมูลภาพที่เลือกไม่ถูกต้อง");
    const bytes = Uint8Array.from(atob(match[2]), ch => ch.charCodeAt(0));
    if (bytes.length > this.maxBytes) throw new Error("Image exceeds 8 MB limit");
    return new Blob([bytes], {type: match[1]});
  }
};
