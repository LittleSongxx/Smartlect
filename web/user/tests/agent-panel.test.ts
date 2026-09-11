import { describe, expect, it } from 'vitest';
import { defineComponent } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { BRAND_EN, BRAND_ZH } from '../src/constants/brand';
import { useOpenAgent } from '../src/composables/useOpenAgent';
import { useDeviceStore } from '../src/stores/device';
import { usePcAgentPanelStore } from '../src/stores/pcAgentPanel';

function mountOpener() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/assistant', component: { template: '<div />' } },
    ],
  });
  const Comp = defineComponent({
    setup() { return useOpenAgent(); },
    template: '<div />',
  });
  const wrapper = mount(Comp, { global: { plugins: [pinia, router] } });
  return { wrapper, router, pinia };
}

describe('品牌与桌面客服浮窗', () => {
  it('英文名 Smartlect，中文名智选商城', () => {
    expect(BRAND_EN).toBe('Smartlect');
    expect(BRAND_ZH).toBe('智选商城');
  });

  it('桌面打开独立会话窗口，不跳整页', async () => {
    const { wrapper, router } = mountOpener();
    await router.push('/');
    await router.isReady();
    useDeviceStore().platform = 'desktop';
    wrapper.vm.openAgent({ draft: '想了解退换货', productId: 'p1', skuKey: 'sku1' });
    const panel = usePcAgentPanelStore();
    expect(panel.visible).toBe(true);
    expect(panel.draft).toBe('想了解退换货');
    expect(panel.productId).toBe('p1');
    expect(panel.skuKey).toBe('sku1');
    expect(router.currentRoute.value.path).toBe('/');
    wrapper.unmount();
  });

  it('手机仍进入助手整页并带上草稿', async () => {
    const { wrapper, router } = mountOpener();
    await router.push('/');
    await router.isReady();
    useDeviceStore().platform = 'mobile';
    wrapper.vm.openAgent({ draft: '查询订单', productId: 'p9', skuKey: 's2' });
    await flushPromises();
    expect(usePcAgentPanelStore().visible).toBe(false);
    expect(router.currentRoute.value.path).toBe('/assistant');
    expect(router.currentRoute.value.query).toMatchObject({
      product: 'p9',
      sku: 's2',
      draft: '查询订单',
    });
    wrapper.unmount();
  });
});
