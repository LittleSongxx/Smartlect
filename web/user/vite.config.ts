import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

const target = process.env.SMARTLECT_GATEWAY_URL || 'http://127.0.0.1:18082';
const port = Number(process.env.SMARTLECT_WEB_USER_PORT || 18180);
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: {
    '@': fileURLToPath(new URL('./src', import.meta.url)),
    // 与 web/admin 共用的唯一 token 源（web/shared/design-tokens.scss）
    '@tokens': fileURLToPath(new URL('../shared/design-tokens.scss', import.meta.url)),
  } },
  css: { preprocessorOptions: { scss: { additionalData: '@use "@tokens" as ds;\n' } } },
  server: { host: '127.0.0.1', port, strictPort: true, allowedHosts: true, fs: { allow: ['..'] }, proxy: { '/api': { target } } },
  preview: { host: '127.0.0.1', port, strictPort: true, allowedHosts: true, proxy: { '/api': { target } } },
});
