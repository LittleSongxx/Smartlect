import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { resetAgentFocus, useAgentFocus } from '../src/composables/useAgentFocus';
import { parseProductContent } from '../src/utils/productContent';

describe('agent focus and product content', () => {
  beforeEach(() => {
    resetAgentFocus();
    setActivePinia(createPinia());
  });

  it('商品路由默认本商品焦点，切全店后不再带 product_id', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/product/:productId', component: { template: '<div />' } }]
    });
    await router.push('/product/p9');
    await router.isReady();
    const wrapper = mount({
      template: '<div />',
      setup() { return useAgentFocus(); }
    }, { global: { plugins: [router] } });
    expect(wrapper.vm.focused).toBe(true);
    expect(wrapper.vm.payload()).toMatchObject({ focus_mode: 'PRODUCT', product_id: 'p9' });
    wrapper.vm.setGlobal();
    expect(wrapper.vm.payload()).toEqual({ focus_mode: 'GLOBAL' });
  });

  it('拒答改问全店与输入条共用同一焦点', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/product/:productId', component: { template: '<div />' } }]
    });
    await router.push('/product/p9');
    await router.isReady();
    const a = mount({ template: '<div />', setup() { return useAgentFocus(); } }, { global: { plugins: [router] } });
    const b = mount({ template: '<div />', setup() { return useAgentFocus(); } }, { global: { plugins: [router] } });
    expect(a.vm.focused).toBe(true);
    b.vm.setGlobal();
    expect(a.vm.payload()).toEqual({ focus_mode: 'GLOBAL' });
    a.vm.setProduct();
    expect(b.vm.payload()).toMatchObject({ focus_mode: 'PRODUCT', product_id: 'p9' });
  });

  it('旧 Markdown 落入 extra，栏目单独解析', () => {
    const parsed = parseProductContent({
      productDesc: '整篇旧文',
      contentJson: JSON.stringify({ ingredients: '水', extra_markdown: '栏目描述' }),
      brand: '智选'
    });
    expect(parsed.brand).toBe('智选');
    expect(parsed.extra).toBe('栏目描述');
    expect(parsed.sections).toEqual([{ key: 'ingredients', label: '成分', text: '水' }]);
  });
});
