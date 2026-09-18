import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import PcSmartlectHomeScreen from '../src/components/home/PcSmartlectHomeScreen.vue';
import { session } from '../src/api/client';
import { mixHomeRecommendations } from '../src/utils/homeRecommendations';

const recommendation = {
  productId: 'p1', productName: '帆布袋', position: 1, recommendation_id: 'rec1',
  propertyValueIds: 'sku1', sku_key: 'hash1', price_cents: 1900, cover: '2026-06/bag.jpg',
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
let wrapper: VueWrapper | undefined;
let calls: { path: string; body: Record<string, any> }[];
let handler: ((path: string, body: Record<string, any>) => Response | Promise<Response> | undefined) | undefined;

beforeEach(() => {
  setActivePinia(createPinia());
  calls = [];
  handler = undefined;
  session.value = {
    actor: { actor_id: 'v1', subject_type: 'visitor', session_id: 's1', execution_scope_id: 'store' },
    csrf_token: 'csrf',
  };
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
    const body = typeof options.body === 'string' ? JSON.parse(options.body) : {};
    calls.push({ path, body });
    const custom = await handler?.(path, body);
    if (custom) return custom;
    if (path.endsWith('/session')) return json(session.value);
    if (path.includes('/recommendations?')) return json({
      recommendation_id: 'rec1', items: [recommendation], ranking_mode: 'rule',
    });
    if (path.includes('/recommendations/rec1/exposures')) return json({ ok: true });
    if (path.includes('/recommendations/rec1/clicks')) return json({ ok: true });
    if (path.endsWith('/traffic/landing')) return json({ ok: true });
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function routerFor() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/catalog', component: { template: '<div />' } },
      { path: '/product/:productId', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
      { path: '/register', component: { template: '<div />' } },
      { path: '/account', component: { template: '<div />' } },
      { path: '/orders', component: { template: '<div />' } },
      { path: '/sign', component: { template: '<div />' } },
      { path: '/member-center', component: { template: '<div />' } },
      { path: '/search', component: { template: '<div />' } },
      { path: '/category/:id', component: { template: '<div />' } },
    ],
  });
  await router.push('/');
  return router;
}

describe('首页确定性推荐', () => {
  it('轮播和精选把推荐插到前面并与热门去重', () => {
    const mixed = mixHomeRecommendations(
      [{ productId: 'p1', productName: '热门帆布袋' }, { productId: 'p2', productName: '杯子' }],
      [recommendation],
      4,
      4
    );
    expect(mixed.map((row) => row.productId)).toEqual(['p1', 'p2']);
    expect(mixed[0]?.kind).toBe('recommend');
    expect(mixed[0]?.recommendation_id).toBe('rec1');
    expect(mixed.some((row) => row.kind === 'hot' && row.productId === 'p1')).toBe(false);
  });

  it('露出后点击记推荐回执并进真详情', async () => {
    const screenRouter = await routerFor();
    wrapper = mount(PcSmartlectHomeScreen, {
      props: {
        categories: [],
        hotProducts: [{ productId: 'p2', productName: '杯子', minPrice: 12 }],
        recommendations: [recommendation],
      },
      global: { plugins: [screenRouter], stubs: { ProductImage: true, ElIcon: true, ElAvatar: true } },
    });
    await flushPromises();
    expect(wrapper.text()).toContain('推荐');
    expect(wrapper.text()).toContain('帆布袋');
    expect(wrapper.text()).not.toContain('广告');
    expect(wrapper.text()).not.toContain('商家推广');
    await wrapper.get('.sl-banner-btn').trigger('click');
    await flushPromises();
    expect(calls.some((call) => call.path.includes('/recommendations/rec1/clicks'))).toBe(true);
    expect(screenRouter.currentRoute.value.path).toBe('/product/p1');
    expect(screenRouter.currentRoute.value.query).toEqual({ sku: 'sku1' });
  });
});
