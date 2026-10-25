(() => {
  if (window.__mangaTranslatorPOCInjected) {
    document.querySelectorAll(".manga-translator-overlay").forEach(node => node.remove());
  }
  window.__mangaTranslatorPOCInjected = true;
  const candidates = [...document.images].filter(img => {
    const r = img.getBoundingClientRect();
    return img.complete && img.naturalWidth >= 350 && img.naturalHeight >= 250
      && r.width > 200 && r.bottom > -300 && r.top < innerHeight + 500;
  }).slice(0, 3);
  for (const image of candidates) {
    const url = image.currentSrc || image.src;
    chrome.runtime.sendMessage({type: "MANGA_FETCH_TRANSLATE", url}, reply => {
      if (chrome.runtime.lastError || !reply?.ok || !image.isConnected) {
        console.warn("Manga Translator:", chrome.runtime.lastError?.message || reply?.error);
        return;
      }
      render(image, reply.data);
    });
  }
  function render(image, result) {
    const parent = image.parentElement;
    if (!parent) return;
    if (getComputedStyle(parent).position === "static") parent.style.position = "relative";
    const layer = document.createElement("div");
    layer.className = "manga-translator-overlay";
    layer.style.cssText = "position:absolute;pointer-events:none;z-index:2147483000;";
    const refresh = () => {
      if (!image.isConnected || !layer.isConnected) return;
      layer.style.left = image.offsetLeft + "px";
      layer.style.top = image.offsetTop + "px";
      layer.style.width = image.offsetWidth + "px";
      layer.style.height = image.offsetHeight + "px";
    };
    for (const region of result.regions || []) {
      const [x,y,w,h] = region.bbox;
      const bubble = document.createElement("div");
      bubble.textContent = region.translated_text;
      bubble.lang = "th";
      bubble.style.cssText = [
        "position:absolute","box-sizing:border-box","display:flex","align-items:center",
        "justify-content:center","text-align:center","overflow:hidden",
        "background:rgba(255,255,255,.93)","color:#111","border-radius:6px",
        "font-family:system-ui,sans-serif","font-weight:600","line-height:1.2",
        "padding:2px","overflow-wrap:anywhere"
      ].join(";");
      bubble.style.left = (x / result.image_width * 100) + "%";
      bubble.style.top = (y / result.image_height * 100) + "%";
      bubble.style.width = (Math.max(40, w) / result.image_width * 100) + "%";
      bubble.style.height = (Math.max(30, h) / result.image_height * 100) + "%";
      bubble.style.fontSize = "clamp(9px,1.5vw,17px)";
      layer.appendChild(bubble);
    }
    parent.appendChild(layer);
    refresh();
    const observer = new ResizeObserver(refresh);
    observer.observe(image);
    setTimeout(() => {
      if (!image.isConnected || !layer.isConnected) observer.disconnect();
    }, 60000);
  }
})();
