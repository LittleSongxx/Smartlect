import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { JSDOM } from 'jsdom';
import AgentProductList from '../src/components/agent/AgentProductList.vue';
import LoginView from '../src/views/LoginView.vue';
import CatalogView from '../src/views/CatalogView.vue';
import ShoppingProfileView from '../src/views/ShoppingProfileView.vue';
import { session } from '../src/api/client';
import { recordLanding } from '../src/api/traffic';
import { useAgentSession } from '../src/composables/useAgentSession';

const actor = { actor_id: 'visitor1', subject_type: 'visitor' as const, session_id: 's1', execution_scope_id: 'store' };
const products = [{ recommendation_id: 'rec1', position: 4, productId: 'p1', propertyValueIds: 'sku1', productName: '背包', stock: 2, price_cents: 1000 },
  { recommendation_id: 'rec1', position: 2, productId: 'p2', propertyValueIds: 'sku2', productName: '收纳袋', stock: 3, price_cents: 2000 }];
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
let wrapper: VueWrapper | undefined;
let observed: Observer[];
class Observer {
  targets: Element[] = [];
  callback: IntersectionObserverCallback;
  observe = (element: Element) => { this.targets.push(element); };
  disconnect = vi.fn();
  constructor(callback: IntersectionObserverCallback) { this.callback = callback; observed.push(this); }
  show(index: number, ratio: number) { this.callback([{ target: this.targets[index], intersectionRatio: ratio, isIntersecting: ratio > 0 } as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
}
beforeEach(() => {
  setActivePinia(createPinia());
  observed = []; useAgentSession().reset();
  session.value = { actor, csrf_token: 'csrf1' };
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  vi.stubGlobal('IntersectionObserver', Observer);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('F3 浏览器触点合同（HTTP 与可见性模拟）', () => {
  it('自然访问每文档只提交一个UUID，不从URL构造渠道或广告触点', async () => {
    const fetch = vi.fn((url: string) => Promise.resolve(json(url.endsWith('/session') ? session.value : { recorded: true }))); vi.stubGlobal('fetch', fetch);
    const results = await Promise.all([recordLanding(), recordLanding(), recordLanding()]);
    expect(results).toEqual([true, true, true]);
    const posts = (fetch.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.endsWith('/traffic/landing'));
    expect(posts).toHaveLength(1);
    const body = JSON.parse(posts[0]![1].body as string);
    expect(Object.keys(body)).toEqual(['entry_id']); expect(body.entry_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(posts[0]![1].signal).toBeInstanceOf(AbortSignal);
  });
  it('只有至少50%可见且页面在前台才曝光，携带服务器position并去重', async () => {
    const fetch = vi.fn((url: string) => Promise.resolve(json(url.endsWith('/session') ? session.value : { recorded: true }))); vi.stubGlobal('fetch', fetch);
    wrapper = mount(AgentProductList, { props: { list: products }, global: { stubs: { ProductImage: true } } }); await flushPromises();
    observed[0]!.show(0, 0.49); await flushPromises();
    expect(fetch.mock.calls).toHaveLength(0);
    observed[0]!.show(0, 0.5); observed[0]!.show(0, 1); await flushPromises();
    let posts = (fetch.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.endsWith('/exposures'));
    expect(posts).toHaveLength(1); expect(JSON.parse(posts[0]![1].body as string)).toEqual({ positions: [4] });
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    observed[0]!.show(1, 1); await flushPromises();
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/exposures'))).toHaveLength(1);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange')); await flushPromises();
    posts = (fetch.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.endsWith('/exposures'));
    expect(posts).toHaveLength(2); expect(JSON.parse(posts[1]![1].body as string)).toEqual({ positions: [2] });
    observed[0]!.show(0, 0); observed[0]!.show(0, 1); await flushPromises();
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/exposures'))).toHaveLength(2);
  });
  it('双击只登记一次，登记失败仍保留用户浏览动作且不提交主体/时间/价格', async () => {
    let finish: (response: Response) => void = () => {};
    const fetch = vi.fn((url: string) => url.endsWith('/session') ? Promise.resolve(json(session.value)) : new Promise<Response>((resolve) => { finish = resolve; })); vi.stubGlobal('fetch', fetch);
    wrapper = mount(AgentProductList, { props: { list: products }, global: { stubs: { ProductImage: true } } }); await flushPromises();
    await wrapper.get('button.product-link').trigger('click'); await wrapper.get('button.product-link').trigger('click'); await flushPromises();
    const posts = (fetch.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.endsWith('/clicks'));
    expect(posts).toHaveLength(1); expect(posts[0]![0]).toBe('/api/assistant/recommendations/rec1/clicks');
    expect(JSON.parse(posts[0]![1].body as string)).toEqual({ position: 4 });
    finish(json({ error: 'temporarily_unavailable' }, 503)); await flushPromises();
    expect(wrapper.emitted('select')).toEqual([[products[0]]]);
  });
  it('没有服务端推荐凭据的普通卡片不伪造曝光和点击', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    wrapper = mount(AgentProductList, { props: { list: [{ productId: 'ordinary', productName: '普通商品', stock: 1 }] }, global: { stubs: { ProductImage: true } } }); await flushPromises();
    expect(observed[0]!.targets).toHaveLength(0);
    await wrapper.get('button.product-link').trigger('click'); expect(fetch).not.toHaveBeenCalled(); expect(wrapper.emitted('select')).toHaveLength(1);
  });
  it.each([true, false])('登录仅绑定当前cookie，原会话是否获服务端迁移授权：%s', async (allowed) => {
    const chat = useAgentSession(); chat.conversationId.value = 'current-visitor-conversation';
    let loggedIn = false;
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/account/checkCode')) return Promise.resolve(json({ code: 200, data: { checkCodeKey: 'captcha1', checkCode: 'data:image/png;base64,' } }));
      if (url.endsWith('/account/login')) { loggedIn = true; return Promise.resolve(json({ code: 200, data: {} })); }
      if (url.endsWith('/session')) return Promise.resolve(json({ actor: loggedIn ? { ...actor, subject_type: 'user', actor_id: 'user1' } : actor, csrf_token: 'current-csrf' }));
      if (url.endsWith('/traffic/bind')) return Promise.resolve(json({ bound: true, conversation_ids: [allowed ? 'current-visitor-conversation' : 'unrelated-conversation'], assignment_conflict: false }));
      if (url.endsWith('/conversations/current-visitor-conversation')) return Promise.resolve(json({ conversation_id: 'current-visitor-conversation', messages: [] }));
      return Promise.resolve(json([]));
    }); vi.stubGlobal('fetch', fetch);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: LoginView }, { path: '/forgot-password', component: { template: '<div />' } }, { path: '/', component: { template: '<div />' } }, { path: '/assistant', component: { template: '<div />' } }] });
    await router.push('/login'); await router.isReady();
    wrapper = mount(LoginView, { global: { plugins: [router] } }); await flushPromises();
    await wrapper.get('input[type=email]').setValue('synthetic@example.invalid'); await wrapper.get('input[type=password]').setValue('synthetic-only');
    await wrapper.get('form').trigger('submit'); await flushPromises();
    const bind = (fetch.mock.calls as unknown as [string, RequestInit][]).find(([url]) => url.endsWith('/traffic/bind'))!;
    expect(JSON.parse(bind[1].body as string)).toEqual({});
    expect(chat.conversationId.value).toBe(allowed ? 'current-visitor-conversation' : '');
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/conversations/unrelated-conversation'))).toBe(false);
    expect(router.currentRoute.value.path).toBe('/');
  });
  it('Catalog仅展示新推荐响应，失败清空列表且不回退旧商品推荐接口', async () => {
    let unavailable = false;
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/session')) return Promise.resolve(json(session.value));
      if (url.includes('/recommendations?')) return Promise.resolve(unavailable ? json({ error: 'recommendation_unavailable' }, 503) : json({ recommendation_id: 'rec1', items: products, assignment_id: 'stable-assignment', strategy_version: 'v1', ranking_mode: 'rule' }));
      return Promise.resolve(json({ recorded: true }));
    }); vi.stubGlobal('fetch', fetch);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: CatalogView }] }); await router.push('/');
    wrapper = mount(CatalogView, { global: { plugins: [router], stubs: { ProductImage: true } } }); await flushPromises();
    expect(wrapper.findAll('.product-tile')).toHaveLength(2);
    expect(wrapper.text()).toContain('背包');
    expect(wrapper.text()).not.toContain('stable-assignment');
    expect(fetch.mock.calls.some(([url]) => url.includes('/recommendations?'))).toBe(true);
    await wrapper.get('input[type=number]').setValue('12.34'); unavailable = true;
    await wrapper.get('form.recommendation-search').trigger('submit'); await flushPromises();
    expect(wrapper.findAll('.product-tile')).toHaveLength(0); expect(wrapper.text()).toContain('推荐暂时不可用');
    expect(fetch.mock.calls.some(([url]) => url.includes('max_price_cents=1234'))).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.includes('limit=8'))).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.includes('/product/loadCommendProduct') || url.includes('/product/loadProduct'))).toBe(false);
  });
  it('原生数字输入的预算偏好仍按精确整数分保存', async () => {
    session.value = { actor: { ...actor, subject_type: 'user', actor_id: 'user1' }, csrf_token: 'csrf1' };
    const fetch = vi.fn((url: string) => Promise.resolve(json(url.endsWith('/session') ? session.value : []))); vi.stubGlobal('fetch', fetch);
    wrapper = mount(ShoppingProfileView, { global: { stubs: { RouterLink: true } } }); await flushPromises();
    await wrapper.get('select').setValue('budget_max_cents'); await wrapper.get('input[type=number]').setValue('19.99');
    await wrapper.get('form').trigger('submit'); await flushPromises();
    const write = (fetch.mock.calls as unknown as [string, RequestInit][]).find(([url, options]) => url.endsWith('/preferences/budget_max_cents') && options.method === 'PUT');
    expect(write).toBeDefined(); expect(JSON.parse(write![1].body as string)).toEqual({ value: 1999 });
  });
});
