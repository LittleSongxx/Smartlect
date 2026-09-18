import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import CatalogView from '../src/views/CatalogView.vue';
import { session } from '../src/api/client';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
let wrapper: VueWrapper | undefined;
let calls: { path: string; body: Record<string, any> }[];
let handler: ((path: string, body: Record<string, any>) => Response | Promise<Response> | undefined) | undefined;
beforeEach(() => {
  setActivePinia(createPinia());
  calls = []; handler = undefined;
  session.value = { actor: { actor_id: 'v1', subject_type: 'visitor', session_id: 's1', execution_scope_id: 'store' }, csrf_token: 'csrf' };
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
    const body = typeof options.body === 'string' ? JSON.parse(options.body) : {}; calls.push({ path, body });
    const custom = await handler?.(path, body); if (custom) return custom;
    if (path.endsWith('/session')) return json(session.value);
    if (path.endsWith('/traffic/landing')) return json({ recorded: true });
    if (path.endsWith('/product/loadCategory')) return json({ code: 200, data: [{ categoryId: 'home', categoryName: '家居' }] });
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('商城导购页行为', () => {
  it('深链只取实际商品详情，返回列表后才请求普通推荐', async () => {
    handler = path => path.endsWith('/product/getProduct') ? json({ code: 200, data: { productInfo: { productId: 'p1', productName: '商品' }, skuList: [] } }) : path.includes('/recommendations?') ? json({ recommendation_id: 'rec1', items: [] }) : undefined;
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/catalog', component: CatalogView }] }); await router.push('/catalog?product=p1&sku=sku1');
    wrapper = mount(CatalogView, { global: { plugins: [router], stubs: { ProductImage: true } } }); await flushPromises();
    expect(wrapper.find('.product-detail').exists()).toBe(true); expect(calls.some(call => call.path.includes('/recommendations?'))).toBe(false);
    await router.push('/catalog'); await flushPromises();
    expect(wrapper.find('.product-detail').exists()).toBe(false); expect(calls.filter(call => call.path.includes('/recommendations?'))).toHaveLength(1);
  });
  it('导购详情渲染 Markdown 图文，有商品参数时不叠列表大标题', async () => {
    handler = path => path.endsWith('/product/getProduct') ? json({ code: 200, data: {
      productInfo: { productId: 'p1', productName: '商品', productDesc: '![](/api/file/getResource?sourceName=2026-06/cover.png)' },
      skuList: []
    } }) : undefined;
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/catalog', component: CatalogView }] });
    await router.push('/catalog?product=p1');
    wrapper = mount(CatalogView, { global: { plugins: [router], stubs: { ProductImage: true } } });
    await flushPromises();
    expect(wrapper.text()).not.toContain('选一件刚好合适的');
    expect(wrapper.find('.markdown-content img').exists()).toBe(true);
    expect(wrapper.find('.markdown-content img').attributes('src')).toBe('/api/file/getResource?sourceName=2026-06/cover.png');
  });
});
