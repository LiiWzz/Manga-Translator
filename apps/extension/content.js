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

  // Translate every eligible loaded image, including lazy-loaded ones discovered later.
  // Budgeted serial dispatch avoids sending the whole page to the API at once.
  const MAX_IMAGES = 120;
  const SEND_INTERVAL_MS = 5500; // server POC budget: 12 translation requests/minute
  const seen = new WeakSet();
  const pending = [];
  let active = false, completed = 0, replaced = 0, skipped = 0;
  let cancelled = false;
  let lastSent = 0;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function eligible(image) {
    return image.isConnected && image.complete &&
      image.naturalWidth >= 350 && image.naturalHeight >= 250 &&
      image.getBoundingClientRect().width > 200 &&
      Boolean(image.currentSrc || image.src);
  }

  function discover() {
    if (cancelled) return;
    for (const image of document.images) {
      if (seen.has(image) || !eligible(image)) continue;
      if (seenCount >= MAX_IMAGES) break;
      seen.add(image);
      seenCount++;
      pending.push(image);
    }
    if (pending.length) drain();
    else if (!active) show("Completed " + completed + " images; " + replaced + " text regions translated, " + skipped + " skipped. Scroll to discover lazy images.");
  }
  let seenCount = 0;
  async function drain() {
    if (active || cancelled) return;
    active = true;
    while (pending.length && !cancelled) {
      const image = pending.shift();
      if (!image.isConnected) continue;
      const delay = Math.max(0, SEND_INTERVAL_MS - (Date.now() - lastSent));
      if (delay) await sleep(delay);
      if (cancelled) break;
      lastSent = Date.now();
      show("Translating page: " + (completed + 1) + "/" + seenCount + " images...");
      try {
        const reply = await new Promise((resolve, reject) => {
          chrome.runtime.sendMessage({type: "MANGA_RENDER_TRANSLATE", url: image.currentSrc || image.src}, response => {
            if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
            resolve(response);
          });
        });
        if (!reply?.ok) throw new Error(reply?.error || "Unknown translation failure");
        if (image.isConnected) {
          replaced += reply.data.applied_regions || 0;
          skipped += (reply.data.skipped || []).length;
          if (reply.data.applied_regions > 0) renderOverlay(image, reply.data.overlay_data_url);
        }
      } catch (error) {
        skipped++;
        console.warn("Manga Translator image failed:", error);
      }
      completed++;
    }
    active = false;
    if (!cancelled) show("Processed " + completed + "/" + seenCount +
      " images, translated " + replaced + " regions; skipped " + skipped +
      ". Scroll down to load more images.");
  }

  function scan() {
    discover();
  }
  document.addEventListener("load", scan, true);
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ["src", "srcset"]});
  cleanup.push(() => {
    cancelled = true;
    document.removeEventListener("load", scan, true);
    observer.disconnect();
  });
  discover();

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
