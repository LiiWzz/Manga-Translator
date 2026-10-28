/* Model selection in a trusted extension page. No inference or credential URLs. */
class ReaderModelPicker {
  constructor({onBusyChange, onOpen = () => {}}) {
    this.onBusyChange = onBusyChange;
    this.picker = document.getElementById("model-picker");
    this.label = document.getElementById("model-current");
    this.count = document.getElementById("model-count");
    this.select = document.getElementById("model-select");
    this.reload = document.getElementById("model-reload");
    this.status = document.getElementById("model-status");
    this.settings = document.getElementById("model-settings");
    this.catalog = [];
    this.optionsKey = null;
    this.selected = null;
    this.version = null;
    this.epoch = 0;
    this.readerBusy = false;
    this.loading = false;
    this.saving = false;
    this.canManage = false;
    this.accountReady = false;
    this.uncertain = false;
    this.message = "กำลังตรวจโมเดล…";
    this.select.addEventListener("change", () => this.save(this.select.value));
    this.reload.addEventListener("click", () => this.loadCatalog());
    this.settings.addEventListener("click", () => chrome.runtime.openOptionsPage());
    this.picker.addEventListener("toggle", () => {
      if (!this.picker.open) return;
      onOpen();
      if (!this.version) this.loadCatalog();
    });
    this.picker.addEventListener("keydown", event => {
      if (event.key === "Escape") { this.picker.open = false; document.getElementById("model-summary").focus(); }
    });
    // Native select popups can return window focus before committing a choice.
    // Keep the open picker stable; its Reload button explicitly refreshes it.
    window.addEventListener("focus", () => { if (!this.picker.open) this.refreshStatus(); });
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== "local" || (!changes.mangaCapability && !changes.mangaSettingsCapability)) return;
      ++this.epoch;
      this.canManage = false;
      this.accountReady = false;
      this.version = null;
      this.catalog = [];
      this.selected = null;
      this.uncertain = false;
      this.message = "การจับคู่เปลี่ยนแล้ว กำลังตรวจสิทธิ์…";
      this.render();
      this.refreshStatus();
    });
    this.render();
    this.refreshStatus();
  }

  async credentials() {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    return chrome.storage.local.get(["mangaCapability", "mangaSettingsCapability"]);
  }
  async request(path, token, options = {}) {
    return fetch("http://127.0.0.1:8000" + path, {cache: "no-store", credentials: "omit", redirect: "error",
      signal: AbortSignal.timeout(15000), ...options,
      headers: {Authorization: "Bearer " + token, ...options.headers}});
  }
  close() { this.picker.open = false; }
  setReaderBusy(value) {
    if (value && !this.readerBusy) this.picker.open = false;
    this.readerBusy = value;
    this.render();
  }
  render() {
    const selected = this.catalog.find(model => model.slug === this.selected);
    this.label.textContent = this.uncertain ? "ตรวจโมเดลอีกครั้ง" : selected?.display_name || this.selected || "ยังไม่ได้เลือก";
    this.label.title = this.label.textContent;
    this.count.textContent = this.catalog.length + " รุ่น";
    this.count.hidden = !this.version || !this.catalog.length;
    const optionsKey = JSON.stringify([this.catalog, selected ? null : this.selected]);
    if (optionsKey !== this.optionsKey) {
      this.select.replaceChildren();
      if (!this.catalog.length || !selected) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = this.selected ? "โมเดลปัจจุบัน: " + this.selected : "เลือกโมเดล";
        option.disabled = true;
        option.selected = true;
        this.select.append(option);
      }
      for (const model of this.catalog) {
        const option = document.createElement("option");
        option.value = model.slug;
        option.textContent = model.display_name;
        option.selected = model.slug === this.selected;
        this.select.append(option);
      }
      this.optionsKey = optionsKey;
    }
    const value = selected ? this.selected : "";
    if (this.select.value !== value) this.select.value = value;
    this.select.disabled = this.readerBusy || this.loading || this.saving || !this.canManage || !this.version || !this.catalog.length;
    this.reload.disabled = this.readerBusy || this.loading || this.saving;
    this.settings.hidden = this.canManage && Boolean(this.version) && this.catalog.length > 0;
    this.status.textContent = this.saving ? "กำลังบันทึกโมเดล…" : this.readerBusy
      ? "รอแปลภาพในคิวให้เสร็จก่อนเปลี่ยนโมเดล" : this.loading ? "กำลังโหลดรายการโมเดล…" : this.message;
  }
  async refreshStatus() {
    if (this.loading || this.saving || this.readerBusy) return;
    const epoch = ++this.epoch;
    this.loading = true;
    this.version = null;
    this.accountReady = false;
    this.render();
    try {
      const credentials = await this.credentials();
      if (epoch !== this.epoch) return;
      this.canManage = Boolean(credentials.mangaSettingsCapability);
      if (!credentials.mangaCapability) {
        this.canManage = false;
        this.selected = null;
        this.message = "เปิด Settings เพื่อจับคู่ส่วนขยายก่อน";
        return;
      }
      const response = await this.request("/api/v1/provider/status", credentials.mangaCapability);
      if (epoch !== this.epoch) return;
      if (response.status === 401 || response.status === 403) { this.canManage = false; throw new Error("pairing"); }
      if (!response.ok) throw new Error("status");
      const data = await response.json();
      if (epoch !== this.epoch) return;
      this.selected = typeof data.model === "string" ? data.model : null;
      this.accountReady = Boolean(data.connected && data.plan_usage_enabled);
      this.version = null;
      this.uncertain = false;
      this.message = !this.canManage ? "การจับคู่เดิมใช้แปลได้ เปิด Settings เพื่ออนุญาตการเปลี่ยนโมเดล"
        : !data.connected || !data.plan_usage_enabled ? "เชื่อมต่อและอนุญาต ChatGPT ใน Settings ก่อน"
          : "เปิดรายการเพื่อเลือกโมเดลที่บัญชีนี้ใช้ได้";
    } catch {
      if (epoch === this.epoch) {
        this.uncertain = true;
        this.message = "ตรวจโมเดลไม่ได้ ตรวจระบบแปลหรือการจับคู่ แล้วกดโหลดรายการใหม่";
      }
    } finally {
      this.loading = false;
      this.render();
      if (epoch !== this.epoch) this.refreshStatus();
      else if (this.canManage && this.accountReady) this.loadCatalog();
    }
  }
  async loadCatalog() {
    if (this.loading || this.saving || this.readerBusy) return;
    const epoch = ++this.epoch;
    this.loading = true;
    this.version = null;
    this.render();
    try {
      const {mangaSettingsCapability: token} = await this.credentials();
      if (epoch !== this.epoch) return;
      if (!token) {
        this.canManage = false;
        this.message = "เปิด Settings เพื่อจับคู่พร้อมสิทธิ์จัดการโมเดลก่อน";
        return;
      }
      const response = await this.request("/api/v1/settings/models", token);
      if (epoch !== this.epoch) return;
      if (response.status === 401 || response.status === 403) {
        this.canManage = false;
        this.message = "สิทธิ์จัดการโมเดลใช้ไม่ได้แล้ว เปิด Settings เพื่อจับคู่ใหม่";
        return;
      }
      if (!response.ok) throw new Error("catalog");
      const data = await response.json();
      if (epoch !== this.epoch) return;
      if (!Array.isArray(data.models) || !/^[a-f0-9]{64}$/.test(data.version) || data.models.some(model =>
        !model || typeof model.slug !== "string" || !model.slug || typeof model.display_name !== "string")) throw new Error("catalog");
      this.catalog = data.models;
      this.selected = typeof data.model === "string" ? data.model : null;
      this.version = data.version;
      this.canManage = true;
      this.uncertain = false;
      this.message = data.models.length ? "พบ " + data.models.length + " โมเดลจากบัญชีนี้ เลือกแล้วบันทึกทันที ใช้กับการแปลครั้งถัดไป"
        : "บัญชีนี้ยังไม่มีโมเดลให้เลือก ลองโหลดใหม่หรือเปิด Settings";
    } catch {
      if (epoch === this.epoch) this.message = "โหลดรายการไม่สำเร็จ คำแปลเดิมยังอยู่ ตรวจการเชื่อมต่อแล้วกดโหลดรายการใหม่";
    } finally {
      this.loading = false;
      this.render();
      if (epoch !== this.epoch) this.refreshStatus();
    }
  }
  async save(slug) {
    if (this.readerBusy || this.loading || this.saving || !this.canManage || !this.version || !this.catalog.some(model => model.slug === slug) || slug === this.selected) {
      this.render(); return;
    }
    const epoch = ++this.epoch;
    this.saving = true;
    this.onBusyChange();
    this.render();
    try {
      const {mangaSettingsCapability: token} = await this.credentials();
      if (epoch !== this.epoch || !token) throw new Error("pairing");
      const response = await this.request("/api/v1/settings/model", token, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({slug, version: this.version})});
      if (epoch !== this.epoch) return;
      if (response.status === 401 || response.status === 403) this.canManage = false;
      if (response.status === 409) {
        this.message = "บัญชีหรือโมเดลถูกเปลี่ยนจากที่อื่น กดโหลดรายการใหม่ก่อนเลือกอีกครั้ง";
        this.uncertain = true;
        this.version = null;
        return;
      }
      if (!response.ok) throw new Error("save");
      const data = await response.json();
      if (epoch !== this.epoch) return;
      if (data.model !== slug || !/^[a-f0-9]{64}$/.test(data.version)) throw new Error("save");
      this.selected = data.model;
      this.version = data.version;
      this.uncertain = false;
      this.message = "บันทึกโมเดลแล้ว ใช้กับการแปลครั้งถัดไป คำแปลบนหน้าจอยังคงอยู่";
    } catch {
      if (epoch === this.epoch) {
        this.uncertain = true;
        this.version = null;
        this.message = this.canManage ? "ยังยืนยันการเปลี่ยนโมเดลไม่ได้ กดโหลดรายการใหม่เพื่อตรวจค่าที่บันทึกไว้ คำแปลเดิมยังอยู่"
          : "สิทธิ์จัดการโมเดลใช้ไม่ได้แล้ว เปิด Settings เพื่อจับคู่ใหม่";
      }
    } finally {
      this.saving = false;
      this.onBusyChange();
      this.render();
      if (epoch !== this.epoch) this.refreshStatus();
    }
  }
}
