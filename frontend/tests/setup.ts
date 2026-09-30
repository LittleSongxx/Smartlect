// vitest 全局准备：修复 jsdom 环境下 localStorage 被复制为无方法空对象的问题。
//
// 现象：测试里 `localStorage.clear is not a function`（14 个用例因此无法运行）。
// 原因：环境把 jsdom 的 Storage 复制到 globalThis 时丢失了原型方法，
// 而 jsdom 内部实例（window._localStorage）是完好的。
// 处置：优先恢复 jsdom 实例；拿不到时退回等价的内存实现，保证用例可跑。

class MemoryStorage implements Storage {
  private data = new Map<string, string>();

  get length(): number {
    return this.data.size;
  }

  clear(): void {
    this.data.clear();
  }

  getItem(key: string): string | null {
    return this.data.has(key) ? this.data.get(key)! : null;
  }

  key(index: number): string | null {
    return [...this.data.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.data.delete(key);
  }

  setItem(key: string, value: string): void {
    this.data.set(key, String(value));
  }
}

const globalStorage = (globalThis as unknown as { localStorage?: Storage }).localStorage;
if (typeof globalStorage?.clear !== "function") {
  const jsdomStorage = (globalThis as unknown as { window?: { _localStorage?: Storage } }).window?._localStorage;
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: typeof jsdomStorage?.clear === "function" ? jsdomStorage : new MemoryStorage(),
  });
}
