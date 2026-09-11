import { createApp } from 'vue';
import { createPinia } from 'pinia';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import * as ElementPlusIconsVue from '@element-plus/icons-vue';
import App from './App.vue';
import router from './router';
import './styles/element-theme.scss';
import './styles/global.scss';
import { useDeviceStore } from './stores/device';
import { installMobileViewportGuards, installVisualViewportSync } from './utils/mobileViewport';
import { ensureLiquidGlassFilters } from './utils/liquidGlassFilters';

ensureLiquidGlassFilters();

const pinia = createPinia();
const deviceStore = useDeviceStore(pinia);
deviceStore.sync();

if (deviceStore.isMobile) {
  installVisualViewportSync();
  installMobileViewportGuards();
}
window.addEventListener('resize', () => deviceStore.sync());

const app = createApp(App);
Object.entries(ElementPlusIconsVue).forEach(([key, component]) => {
  app.component(key, component);
});
app.use(pinia);
app.use(router);
app.use(ElementPlus);
app.mount('#app');
