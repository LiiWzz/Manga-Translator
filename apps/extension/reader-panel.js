/* Non-destructive side panel: translation and edits never modify page images. */
const status = document.getElementById("status");
const items = document.getElementById("items");
const cache = new Map();
let generation = 0;
let context = "";
let running = false;

function show(message) { status.textContent = message; }
function element(tag, className, value) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (value != null) el.textContent = value;
  return el;
}
function render(data, url) {
  data.regions.forEach((r, index) => {
    const card = element("section", "item");
    const label = element("small", "", "ภาพ " + (data.imageIndex + 1) + " · บทสนทนา " + (index + 1));
    const original = element("div", "source", r.source_text);
    const translated = element("div", "translation", r.translated_text);
    const controls = element("div", "tools");
    const edit = element("button", "", "แก้คำแปล");
    const locate = element("button", "", "ไปยังภาพ");
    edit.addEventListener("click", () => {
      const input = document.createElement("textarea");
      input.value = translated.textContent;
      const save = element("button", "", "บันทึก");
      save.addEventListener("click", () => {
        translated.textContent = input.value;
        input.remove();
        save.remove();
        data.regions[index].translated_text = translated.textContent;
      });
      card.append(input, save);
      input.focus();
    });
    locate.addEventListener("click", async () => {
      try {
        await chrome.tabs.sendMessage(data.tabId, {type:"MANGA_READER_LOCATE", index:data.imageIndex});
      } catch { show("ไม่สามารถค้นหาภาพได้ กรุณารีเฟรชหน้าเว็บ"); }
    });
    controls.append(edit, locate);
    card.append(label, original, translated, controls);
    items.append(card);
  });
}

async function scan() {
  if (running) return;
  running = true;
  const task = ++generation;
  document.getElementById("scan").disabled = true;
  try {
    const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
    if (!tab?.id || !/^https?:/.test(tab.url || "")) throw new Error("เปิดหน้ามังงะก่อน");
    const images = await chrome.tabs.sendMessage(tab.id, {type:"MANGA_READER_DISCOVER"});
    if (!Array.isArray(images) || !images.length) throw new Error("ไม่พบภาพที่โหลดแล้วในบริเวณหน้าจอ");
    for (let i = 0; i < images.length; i++) {
      if (task !== generation) break;
      const image = images[i];
      const key = tab.id + ":" + image.url;
      let data = cache.get(key);
      if (!data) {
        show("กำลังแปล " + (i + 1) + "/" + images.length);
        const reply = await chrome.runtime.sendMessage({type:"MANGA_READER_TRANSLATE",url:image.url,context:context.slice(-1500)});
        if (!reply?.ok) {show("ภาพ " + (i+1) + ": " + (reply?.error || "แปลไม่สำเร็จ")); continue;}
        data = reply.data;
        cache.set(key, data);
      }
      data.imageIndex = image.index;
      data.tabId = tab.id;
      render(data, image.url);
      context = (context + " " + data.regions.map(r=>r.source_text+" => "+r.translated_text).join(" ")).slice(-1500);
    }
    show("เสร็จสิ้น · แปลเพิ่มเมื่อเลื่อนหน้าแล้วกดปุ่มอีกครั้ง");
  } catch(e) {show(e.message || String(e));}
  finally {running = false;document.getElementById("scan").disabled = false;}
}
document.getElementById("scan").addEventListener("click",scan);
document.getElementById("reset").addEventListener("click",()=>{
  ++generation;cache.clear();context="";items.replaceChildren();show("เริ่มใหม่แล้ว");
});
document.getElementById("settings").addEventListener("click",()=>chrome.runtime.openOptionsPage());
