import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@tokens': fileURLToPath(new URL('../shared/design-tokens.scss', import.meta.url))
    }
  },
  css: { preprocessorOptions: { scss: { additionalData: '@use "@tokens" as ds;\n' } } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['./tests/**/*.test.ts'],
    css: false,
    clearMocks: true
  }
});
