import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import PromotionCard from '../src/components/PromotionCard.vue';
import CatalogView from '../src/views/CatalogView.vue';
import { session } from '../src/api/client';
import type { Promotion } from '../src/api/traffic';

const promotion: Promotion = { creative_id: 'cr1', campaign_id: 'ca1', productId: 'p1', sku_key: 'hash1', propertyValueIds: 'sku1', productName: '帆布袋', copy_text: '认识这件商品', price_cents: 1900, stock: 2, specification: '原色', creative_version: 2, campaign_version: 3 };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
let wrapper: VueWrapper | undefined;
let observers: Observer[];
class Observer {
  callback: IntersectionObserverCallback; targets: Element[] = [];
  constructor(callback: IntersectionObserverCallback) { this.callback = callback; observers.push(this); }
  observe(element: Element) { this.targets.push(element); }
  disconnect() {}
  show(ratio: number) { this.callback([{ target: this.targets[0], intersectionRatio: ratio, isIntersecting: ratio > 0 } as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
}
let calls: { path: string; body: Record<string, any> }[];
let handler: ((path: string, body: Record<string, any>) => Response | Promise<Response> | undefined) | undefined;
beforeEach(() => {
  setActivePinia(createPinia());
  calls = []; observers = []; handler = undefined;
  session.value = { actor: { actor_id: 'v1', subject_type: 'visitor', session_id: 's1', execution_scope_id: 'store' }, csrf_token: 'csrf' };
  vi.stubGlobal('IntersectionObserver', Observer);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
    const body = typeof options.body === 'string' ? JSON.parse(options.body) : {}; calls.push({ path, body });
    const custom = await handler?.(path, body); if (custom) return custom;
    if (path.endsWith('/session')) return json(session.value);
    if (path.endsWith('/traffic/landing')) return json({ recorded: true });
    if (path.endsWith('/product/loadCategory')) return json({ code: 200, data: [{ categoryId: 'home', categoryName: '家居' }] });
    if (path.endsWith('/ads/exposures')) return json({ ...body, creative_version: 2, campaign_version: 3 });
    if (path.endsWith('/ads/clicks')) return json({ ...body, status: 'CHARGED' });
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const renderCard = async () => { wrapper = mount(PromotionCard, { props: { item: promotion }, global: { stubs: { ProductImage: true } } }); await flushPromises(); return wrapper; };

describe('商城推广与推荐的独立浏览器行为', () => {
  it('渲染不曝光不扣费；50%可见且页面前台才登记，重复可见不重发', async () => {
    await renderCard(); expect(calls).toHaveLength(0);
    observers[0]!.show(.49); await flushPromises(); expect(calls).toHaveLength(0);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden'); observers[0]!.show(1); await flushPromises(); expect(calls).toHaveLength(0);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')); await flushPromises();
    observers[0]!.show(0); observers[0]!.show(1); await flushPromises();
    const exposures = calls.filter(call => call.path.endsWith('/ads/exposures'));
    expect(exposures).toHaveLength(1); expect(exposures[0]!.body).toMatchObject({ creative_id: 'cr1', expected_campaign_version: 3, expected_creative_version: 2 });
    expect(calls.some(call => call.path.endsWith('/clicks'))).toBe(false);
  });
  it('点击等待原曝光回执；双击只发送一次CPC，并使用服务端原回执进入商品详情', async () => {
    let resolve: (response: Response) => void = () => {};
    handler = (path, body) => path.endsWith('/ads/exposures') ? new Promise<Response>(done => { resolve = response => done(response); }) : undefined;
    const card = await renderCard(); observers[0]!.show(1); await flushPromises();
    await card.get('button').trigger('click'); await card.get('button').trigger('click'); await flushPromises();
    expect(calls.some(call => call.path.endsWith('/clicks'))).toBe(false);
    const exposure = calls.find(call => call.path.endsWith('/ads/exposures'))!.body;
    resolve(json({ ...exposure, creative_version: 2, campaign_version: 3 })); await flushPromises();
    expect(calls.filter(call => call.path.endsWith('/ads/clicks'))).toHaveLength(1);
    expect(calls.find(call => call.path.endsWith('/ads/clicks'))!.body.exposure_id).toBe(exposure.exposure_id);
    expect(card.emitted('select')).toEqual([[promotion]]);
    expect(calls.some(call => call.path.includes('/recommendations/'))).toBe(false);
  });
  it.each(['exposure', 'click'])('投放暂停或版本变化在%s阶段拒绝时只显示刷新入口，不伪造跳转或新曝光', async (stage) => {
    handler = path => path.endsWith(stage === 'exposure' ? '/ads/exposures' : '/ads/clicks') ? json({ detail: 'ads_not_active' }, 409) : undefined;
    const card = await renderCard(); observers[0]!.show(1); await flushPromises();
    if (stage === 'click') { await card.get('button').trigger('click'); await flushPromises(); }
    expect(card.text()).toContain('可投状态已变化'); expect(card.emitted('select')).toBeUndefined();
    await card.get('button').trigger('click'); expect(card.emitted('refresh')).toHaveLength(1);
    expect(calls.filter(call => call.path.endsWith('/ads/exposures'))).toHaveLength(1);
  });
  it('不确定点击结果只重试原幂等ID，切换身份后不继续进入旧商品', async () => {
    let failed = false;
    handler = path => { if (path.endsWith('/ads/clicks') && !failed) { failed = true; throw new TypeError('Network unavailable'); } };
    const card = await renderCard(); observers[0]!.show(1); await flushPromises();
    await card.get('button').trigger('click'); await flushPromises(); expect(card.emitted('select')).toBeUndefined();
    await card.get('button').trigger('click'); await flushPromises();
    const clicks = calls.filter(call => call.path.endsWith('/ads/clicks')); expect(clicks).toHaveLength(2); expect(clicks[0]!.body).toEqual(clicks[1]!.body);
    session.value!.actor.actor_id = 'v2'; await card.get('button').trigger('click'); await flushPromises();
    expect(calls.filter(call => call.path.endsWith('/ads/clicks'))).toHaveLength(2); expect(card.emitted('select')).toHaveLength(1);
  });
  it('广告深链只取实际商品详情，返回列表后才请求普通推荐', async () => {
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
