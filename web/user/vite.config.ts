import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

const target = process.env.SMARTLECT_GATEWAY_URL || 'http://127.0.0.1:18082';
const port = Number(process.env.SMARTLECT_WEB_USER_PORT || 18180);
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port, strictPort: true, proxy: { '/api': { target } } },
  preview: { host: '127.0.0.1', port, strictPort: true, proxy: { '/api': { target } } },
});
