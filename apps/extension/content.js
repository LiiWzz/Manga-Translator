(() => {
  // This file is injected each time the toolbar button is clicked.
  // Clean up previous overlay images/listeners first, then translate again.
  window.__mangaTranslatorCleanup?.();
  const cleanup = [];
  window.__mangaTranslatorCleanup = () => {
    for (const dispose of cleanup) dispose();
    cleanup.length = 0;
  };

  const status = document.createElement("div");
  status.setAttribute("role", "status");
  status.style.cssText = [
    "position:fixed", "bottom:16px", "right:16px", "z-index:2147483647",
    "background:rgba(17,17,17,.93)", "color:white", "padding:10px 14px",
    "font:13px/1.5 system-ui,sans-serif", "border-radius:8px",
    "max-width:340px", "pointer-events:none", "box-shadow:0 3px 15px #0005"
  ].join(";");
  document.documentElement.appendChild(status);
  cleanup.push(() => status.remove());
  const show = message => {status.textContent = "Manga Translator: " + message;};

  const candidates = [...document.images].filter(img => {
    const rect = img.getBoundingClientRect();
    return img.complete && img.naturalWidth >= 350 && img.naturalHeight >= 250
      && rect.width > 200 && rect.bottom > -300 && rect.top < innerHeight + 500;
  }).slice(0, 3);

  if (!candidates.length) {
    show("No eligible image in the current viewport.");
    return;
  }
  let completed = 0, replaced = 0, skipped = 0;
  show("Processing " + candidates.length + " images...");
  for (const image of candidates) {
    const url = image.currentSrc || image.src;
    chrome.runtime.sendMessage({type: "MANGA_RENDER_TRANSLATE", url}, reply => {
      if (chrome.runtime.lastError || !reply?.ok) {
        console.warn("Manga Translator:", chrome.runtime.lastError?.message || reply?.error);
      } else if (!image.isConnected) {
        console.warn("Manga Translator: image was removed before translation completed");
      } else {
        replaced += reply.data.applied_regions || 0;
        skipped += (reply.data.skipped || []).length;
        if (reply.data.applied_regions > 0) renderOverlay(image, reply.data.overlay_data_url);
        if (reply.data.provider === "mock") {
          console.warn("Manga Translator: mock provider does not translate to Thai. Configure OPENAI_API_KEY on the backend.");
        }
      }
      completed++;
      if (completed === candidates.length) {
        show(replaced
          ? "Translated " + replaced + " text regions; skipped " + skipped + " unsafe regions."
          : "No Thai rendered. Check AI provider and OCR/bubble detection in backend logs.");
        setTimeout(() => { if (status.isConnected) status.remove(); }, 9000);
      }
    });
  }

  function renderOverlay(image, url) {
    const overlay = document.createElement("img");
    overlay.className = "manga-translator-v02-layer";
    overlay.alt = "";
    overlay.setAttribute("aria-hidden", "true");
    overlay.src = url;
    overlay.style.cssText = [
      "position:fixed", "z-index:2147483000", "pointer-events:none",
      "display:block", "margin:0", "padding:0", "border:0", "max-width:none",
      "max-height:none", "opacity:1"
    ].join(";");
    const originalStyles = getComputedStyle(image);
    overlay.style.objectFit = originalStyles.objectFit;
    overlay.style.objectPosition = originalStyles.objectPosition;
    overlay.style.borderRadius = originalStyles.borderRadius;
    document.documentElement.appendChild(overlay);

    let pending = false;
    const update = () => {
      pending = false;
      if (!image.isConnected) {
        overlay.remove();
        return;
      }
      const rect = image.getBoundingClientRect();
      overlay.style.left = rect.left + "px";
      overlay.style.top = rect.top + "px";
      overlay.style.width = rect.width + "px";
      overlay.style.height = rect.height + "px";
      overlay.style.visibility = rect.width && rect.height ? "visible" : "hidden";
    };
    const schedule = () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(update);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(image);
    addEventListener("scroll", schedule, {passive: true, capture: true});
    addEventListener("resize", schedule, {passive: true});
    update();
    cleanup.push(() => {
      observer.disconnect();
      removeEventListener("scroll", schedule, true);
      removeEventListener("resize", schedule);
      overlay.remove();
    });
  }
})();
