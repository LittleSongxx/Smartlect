import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
const target = process.env.SMARTLECT_GATEWAY_URL || 'http://127.0.0.1:18082';
const port = Number(process.env.SMARTLECT_WEB_ADMIN_PORT || 18181);
export default defineConfig({
  base: '/admin/', plugins: [vue()],
  resolve: { alias: {
    '@': fileURLToPath(new URL('./src', import.meta.url)),
    // 与 web/user 共用的唯一 token 源（web/shared/design-tokens.scss）
    '@tokens': fileURLToPath(new URL('../shared/design-tokens.scss', import.meta.url)),
  } },
  css: { preprocessorOptions: { scss: { additionalData: '@use "@tokens" as ds;\n' } } },
  server: { host: '127.0.0.1', port, strictPort: true, fs: { allow: ['..'] }, proxy: { '/admin-api': { target } } },
  preview: { host: '127.0.0.1', port, strictPort: true, proxy: { '/admin-api': { target } } },
  test: { environment: 'jsdom', include: ['tests/**/*.test.js'] },
});
