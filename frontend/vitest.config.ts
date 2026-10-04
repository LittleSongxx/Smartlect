import { defineConfig } from "vitest/config";

// 单测统一跑在 jsdom 环境；setup 恢复被环境复制破坏的 localStorage。
export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["tests/setup.ts"],
  },
});
