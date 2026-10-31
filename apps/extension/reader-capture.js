/* A local preview: only the confirmed crop is submitted for translation. */
class ReaderCapture {
  constructor({onConfirm, onChange, onError}) {
    this.onConfirm = onConfirm;
    this.onChange = onChange;
    this.onError = onError;
    this.root = document.getElementById("capture-preview");
    this.surface = document.getElementById("capture-surface");
    this.image = document.getElementById("capture-image");
    this.outline = document.getElementById("capture-selection");
    this.label = document.getElementById("capture-size");
    this.confirm = document.getElementById("capture-confirm");
    this.cancel = document.getElementById("capture-cancel");
    this.open = false;
    this.version = 0;
    this.cancel.addEventListener("click", () => this.cancelSelection());
    document.getElementById("capture-all").addEventListener("click", () => {
      this.box = {x: 0, y: 0, width: 1, height: 1}; this.render();
    });
    this.surface.addEventListener("pointerdown", event => {
      if (!this.open || event.button !== 0) return;
      event.preventDefault();
      this.anchor = this.point(event);
      this.surface.setPointerCapture(event.pointerId);
    });
    this.surface.addEventListener("pointermove", event => {
      if (!this.anchor) return;
      const point = this.point(event);
      this.box = {x: Math.min(this.anchor.x, point.x), y: Math.min(this.anchor.y, point.y),
        width: Math.abs(point.x - this.anchor.x), height: Math.abs(point.y - this.anchor.y)};
      this.render();
    });
    for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
      this.surface.addEventListener(name, () => { this.anchor = null; });
    }
    this.surface.addEventListener("keydown", event => {
      if (event.key === "Escape") { this.cancelSelection(); return; }
      const axes = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
      if (!this.open || !axes[event.key]) return;
      event.preventDefault();
      const [x, y] = axes[event.key], b = this.box;
      if (event.shiftKey) {
        b.width = Math.max(.01, Math.min(1 - b.x, b.width + x * .01));
        b.height = Math.max(.01, Math.min(1 - b.y, b.height + y * .01));
      } else {
        b.x = Math.max(0, Math.min(1 - b.width, b.x + x * .01));
        b.y = Math.max(0, Math.min(1 - b.height, b.y + y * .01));
      }
      this.render();
    });
    this.confirm.addEventListener("click", () => {
      if (!this.open || this.confirm.disabled) return;
      try {
        const rect = ReaderCapture.pixels(this.box, this.image.naturalWidth, this.image.naturalHeight);
        const canvas = document.createElement("canvas");
        canvas.width = rect.width; canvas.height = rect.height;
        canvas.getContext("2d").drawImage(this.image, rect.x, rect.y, rect.width, rect.height, 0, 0, rect.width, rect.height);
        const dataUrl = canvas.toDataURL("image/png");
        if (dataUrl.length > Math.ceil(8 * 1024 * 1024 / 3) * 4 + 64) throw new Error("พื้นที่ที่เลือกใหญ่เกิน 8 MB กรุณาเลือกพื้นที่เล็กลง");
        const context = this.context;
        this.close();
        return Promise.resolve(this.onConfirm(dataUrl, context)).catch(error => this.onError(error.message));
      } catch (error) { this.onError(error.message); }
    });
  }

  static pixels(box, width, height) {
    const x = Math.max(0, Math.min(width - 1, Math.floor(box.x * width)));
    const y = Math.max(0, Math.min(height - 1, Math.floor(box.y * height)));
    return {x, y, width: Math.max(1, Math.min(width - x, Math.round(box.width * width))),
      height: Math.max(1, Math.min(height - y, Math.round(box.height * height)))};
  }
  point(event) {
    const rect = this.surface.getBoundingClientRect();
    return {x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))};
  }
  async show(dataUrl, context) {
    this.close();
    const version = this.version;
    this.image.src = dataUrl;
    try { await this.image.decode(); }
    catch { if (version === this.version) this.close(); throw new Error("เปิดภาพหน้าจอไม่ได้ กรุณาลองใหม่"); }
    if (version !== this.version) return;
    if (!this.image.naturalWidth || !this.image.naturalHeight || this.image.naturalWidth * this.image.naturalHeight > 24000000) {
      this.close(); throw new Error("ภาพหน้าจอใหญ่เกิน 24 MP กรุณาลดขนาดหน้าต่างแล้วลองใหม่");
    }
    this.context = context;
    this.box = {x: 0, y: 0, width: 1, height: 1};
    this.open = true;
    this.root.hidden = false;
    this.render();
    this.surface.focus();
    this.onChange();
  }
  render() {
    const b = this.box, rect = ReaderCapture.pixels(b, this.image.naturalWidth, this.image.naturalHeight);
    Object.assign(this.outline.style, {left: b.x * 100 + "%", top: b.y * 100 + "%", width: b.width * 100 + "%", height: b.height * 100 + "%"});
    this.label.textContent = "พื้นที่ที่จะส่งแปล " + rect.width + " × " + rect.height + " px";
    this.confirm.disabled = rect.width < 16 || rect.height < 16;
  }
  close() {
    ++this.version;
    this.open = false;
    this.anchor = null;
    this.context = null;
    this.image.removeAttribute("src");
    this.root.hidden = true;
    this.onChange();
  }
  cancelSelection() {
    this.close();
    this.onError("ยกเลิกเลือกพื้นที่แล้ว ยังไม่ได้ส่งแปล");
    document.getElementById("capture").focus();
  }
}
