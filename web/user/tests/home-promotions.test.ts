import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import AdSlot from '../src/components/home/AdSlot.vue';
import PcSmartlectHomeScreen from '../src/components/home/PcSmartlectHomeScreen.vue';
import { session } from '../src/api/client';
import type { Promotion } from '../src/api/traffic';
import { mixHomeAds } from '../src/utils/homeAds';

const promotion: Promotion = {
  creative_id: 'cr1', campaign_id: 'ca1', productId: 'p1', sku_key: 'hash1', propertyValueIds: 'sku1',
  productName: '帆布袋', copy_text: '认识这件商品', price_cents: 1900, stock: 2, specification: '原色',
  creative_version: 2, campaign_version: 3, cover: '2026-06/bag.jpg',
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
let wrapper: VueWrapper | undefined;
let observers: Observer[];
class Observer {
  callback: IntersectionObserverCallback;
  targets: Element[] = [];
  constructor(callback: IntersectionObserverCallback) { this.callback = callback; observers.push(this); }
  observe(element: Element) { this.targets.push(element); }
  disconnect() {}
  show(ratio: number) {
    this.callback([{
      target: this.targets[0], intersectionRatio: ratio, isIntersecting: ratio > 0,
    } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
}
let calls: { path: string; body: Record<string, any> }[];
let handler: ((path: string, body: Record<string, any>) => Response | Promise<Response> | undefined) | undefined;

beforeEach(() => {
  setActivePinia(createPinia());
  calls = [];
  observers = [];
  handler = undefined;
  session.value = {
    actor: { actor_id: 'v1', subject_type: 'visitor', session_id: 's1', execution_scope_id: 'store' },
    csrf_token: 'csrf',
  };
  vi.stubGlobal('IntersectionObserver', Observer);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
    const body = typeof options.body === 'string' ? JSON.parse(options.body) : {};
    calls.push({ path, body });
    const custom = await handler?.(path, body);
    if (custom) return custom;
    if (path.endsWith('/session')) return json(session.value);
    if (path.includes('/ads/recommendations?')) return json({ items: [promotion], ranking_mode: 'rule' });
    if (path.endsWith('/ads/exposures')) return json({ ...body, creative_version: 2, campaign_version: 3 });
    if (path.endsWith('/ads/clicks')) return json({ ...body, status: 'CHARGED' });
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

describe('首页隐式广告', () => {
  it('轮播和精选把广告插到前面并与热门去重', () => {
    const mixed = mixHomeAds(
      [{ productId: 'p1', productName: '热门帆布袋' }, { productId: 'p2', productName: '杯子' }],
      [promotion],
      2,
      4
    );
    expect(mixed.map((row) => row.productId)).toEqual(['p1', 'p2']);
    expect(mixed[0]?.kind).toBe('ad');
    expect(mixed[0]?.promotion?.creative_id).toBe('cr1');
    expect(mixed.some((row) => row.kind === 'hot' && row.productId === 'p1')).toBe(false);
  });

  it('露出记曝光，点击 CHARGED 后进真详情而不是导购页', async () => {
    const router = await routerFor();
    wrapper = mount(AdSlot, {
      props: { item: promotion },
      slots: { default: '<span class="ad-pill">广告</span>' },
      global: { plugins: [router] },
    });
    await flushPromises();
    expect(wrapper.text()).toContain('广告');
    expect(calls.some((call) => call.path.endsWith('/ads/exposures') || call.path.endsWith('/ads/clicks'))).toBe(false);
    observers[0]!.show(1);
    await flushPromises();
    expect(calls.some((call) => call.path.endsWith('/ads/exposures'))).toBe(true);
    await wrapper.get('button').trigger('click');
    await flushPromises();
    expect(calls.some((call) => call.path.endsWith('/ads/clicks'))).toBe(true);
    expect(router.currentRoute.value.path).toBe('/');
    wrapper.unmount();

    const screenRouter = await routerFor();
    wrapper = mount(PcSmartlectHomeScreen, {
      props: {
        categories: [],
        hotProducts: [{ productId: 'p2', productName: '杯子', minPrice: 12 }],
        promotions: [promotion],
      },
      global: { plugins: [screenRouter], stubs: { ProductImage: true, ElIcon: true, ElAvatar: true } },
    });
    await flushPromises();
    expect(wrapper.text()).toContain('广告');
    expect(wrapper.text()).toContain('帆布袋');
    expect(wrapper.text()).not.toContain('商家推广');
    const adObservers = observers.filter((row) => row.targets.length);
    adObservers.at(-1)?.show(1);
    await flushPromises();
    await wrapper.get('.sl-banner-btn').trigger('click');
    await flushPromises();
    expect(screenRouter.currentRoute.value.path).toBe('/product/p1');
    expect(screenRouter.currentRoute.value.query).toEqual({ sku: 'sku1' });
  });
});
