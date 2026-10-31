/* Local dialogue storage. Only the service worker writes this namespace. */
class ReaderCache {
  static storageKey = "mangaReaderCacheV1";
  constructor(storage, {now = Date.now, maxBytes = 4 * 1024 * 1024, maxEntries = 200,
    ttl = 7 * 24 * 60 * 60 * 1000} = {}) {
    this.storage = storage;
    this.now = now;
    this.maxBytes = maxBytes;
    this.maxEntries = maxEntries;
    this.ttl = ttl;
    this.queue = Promise.resolve();
  }
  serial(operation) {
    const result = this.queue.then(operation);
    this.queue = result.catch(() => {});
    return result;
  }
  static data(value) {
    if (!value || !Array.isArray(value.regions) || value.regions.length > 40) throw new Error("Invalid cached dialogue");
    return {
      image_width: Number(value.image_width) || 0, image_height: Number(value.image_height) || 0,
      regions: value.regions.map(row => {
        if (typeof row?.source_text !== "string" || typeof row.translated_text !== "string" ||
            row.source_text.length > 700 || row.translated_text.length > 1000) throw new Error("Invalid cached dialogue");
        return {source_text: row.source_text, translated_text: row.translated_text, bbox: null, confidence: null};
      }),
      reader_mode: "vision-first"
    };
  }
  async load() {
    const value = (await this.storage.get(ReaderCache.storageKey))[ReaderCache.storageKey];
    const root = value?.version === 1 && typeof value.epoch === "string" && Array.isArray(value.entries)
      ? {version: 1, epoch: value.epoch, entries: value.entries}
      : {version: 1, epoch: crypto.randomUUID(), entries: []};
    root.entries = root.entries.filter(entry => {
      if (!/^[a-f0-9]{64}$/.test(entry?.key) || !Number.isFinite(entry.created) ||
          !Number.isFinite(entry.used) || entry.created > this.now() || this.now() - entry.created >= this.ttl) return false;
      try {
        entry.data = ReaderCache.data(entry.data);
        const edits = {};
        for (const [index, text] of Object.entries(entry.edits || {})) {
          if (!/^\d+$/.test(index) || !entry.data.regions[Number(index)] ||
              typeof text !== "string" || !text.trim() || text.length > 1000) return false;
          edits[index] = text;
        }
        entry.edits = edits;
        return true;
      } catch { return false; }
    }).map(entry => ({key: entry.key, created: entry.created, used: entry.used, data: entry.data, edits: entry.edits}));
    this.needsWrite = JSON.stringify(value) !== JSON.stringify(root) || root.entries.length > this.maxEntries ||
      new TextEncoder().encode(JSON.stringify(root)).length > this.maxBytes;
    return root;
  }
  async write(root) {
    const size = () => new TextEncoder().encode(JSON.stringify(root)).length;
    root.entries.sort((a, b) => a.used - b.used);
    while (root.entries.length && (root.entries.length > this.maxEntries || size() > this.maxBytes)) root.entries.shift();
    if (size() > this.maxBytes) throw new Error("Reader cache limit is too small");
    await this.storage.set({[ReaderCache.storageKey]: root});
  }
  begin() {
    return this.serial(async () => {
      const root = await this.load();
      if (this.needsWrite) await this.write(root);
      return root.epoch;
    });
  }
  get(key, epoch) {
    return this.serial(async () => {
      const root = await this.load();
      const entry = root.epoch === epoch && root.entries.find(row => row.key === key);
      if (entry) {
        entry.used = this.now();
        root.entries = root.entries.filter(row => row !== entry).concat(entry);
      }
      if (entry || this.needsWrite) await this.write(root);
      if (!entry) return null;
      const data = ReaderCache.data(entry.data);
      for (const [index, text] of Object.entries(entry.edits)) data.regions[Number(index)].translated_text = text;
      return data;
    });
  }
  put(key, data, epoch) {
    return this.serial(async () => {
      const root = await this.load();
      if (root.epoch !== epoch) return false; // Clear-data also fences in-flight requests.
      if (!/^[a-f0-9]{64}$/.test(key)) throw new Error("Invalid Reader cache key");
      if (root.entries.some(entry => entry.key === key)) return true;
      const entry = {key, data: ReaderCache.data(data), edits: {}, created: this.now(), used: this.now()};
      root.entries = root.entries.filter(row => row.key !== key);
      root.entries.push(entry);
      await this.write(root);
      return root.entries.includes(entry);
    });
  }
  edit(key, index, text, epoch) {
    return this.serial(async () => {
      const root = await this.load();
      if (root.epoch !== epoch) throw new Error("ข้อมูลถูกลบแล้ว กรุณาแปลภาพอีกครั้ง");
      const entry = root.entries.find(row => row.key === key);
      if (!entry || !Number.isInteger(index) || !entry.data.regions[index]) throw new Error("คำแปลที่บันทึกไว้หมดอายุหรือถูกลบแล้ว กรุณาแปลภาพอีกครั้ง");
      if (typeof text !== "string" || !text.trim() || text.length > 1000) throw new Error("คำแปลต้องมีข้อความไม่เกิน 1000 ตัวอักษร");
      entry.edits[index] = text;
      entry.used = this.now();
      root.entries = root.entries.filter(row => row !== entry).concat(entry);
      await this.write(root);
      if (!root.entries.includes(entry)) throw new Error("พื้นที่บันทึกคำแปลไม่เพียงพอ");
    });
  }
  clear() {
    return this.serial(async () => {
      await this.write({version: 1, epoch: crypto.randomUUID(), entries: []});
    });
  }
}
if (typeof module !== "undefined") module.exports = {ReaderCache};
