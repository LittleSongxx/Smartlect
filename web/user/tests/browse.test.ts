import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import BrowseView from '../src/views/BrowseView.vue';
import { session } from '../src/api/client';
import { clearProductScopeCache } from '../src/utils/productScope';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const product = (id: string, name: string) => ({ productId: id, productName: name, minPrice: 19, cover: '', totalSale: 3 });
let wrapper: VueWrapper | undefined;
let calls: { path: string; body: Record<string, string> }[];
let page: { list: Record<string, any>[]; totalCount: number; pageTotal: number };

class Observer {
  constructor(_callback: IntersectionObserverCallback) {}
  observe() {}
  disconnect() {}
}

beforeEach(() => {
  clearProductScopeCache();
  calls = [];
  page = { list: [product('p1', '陶瓷杯'), product('p2', '静音键盘')], totalCount: 2, pageTotal: 1 };
  session.value = { actor: { actor_id: 'v1', subject_type: 'visitor', session_id: 's1', execution_scope_id: 'store' }, csrf_token: 'csrf' };
  vi.stubGlobal('IntersectionObserver', Observer);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
    // javaPost sends a URLSearchParams instance, not a string.
    const raw = options.body;
    const body = Object.fromEntries(raw instanceof URLSearchParams ? raw : new URLSearchParams(typeof raw === 'string' ? raw : ''));
    calls.push({ path, body });
    if (path.endsWith('/session')) return json(session.value);
    if (path.endsWith('/catalog/scope')) return json({ include: null, exclude: [] });
    if (path.endsWith('/traffic/landing')) return json({ recorded: true });
    if (path.endsWith('/product/loadCategory')) return json({ code: 200, data: [
      { categoryId: 'home', categoryName: '家居' }, { categoryId: 'digital', categoryName: '数码' }] });
    if (path.endsWith('/product/loadProduct')) return json({ code: 200, data: page });
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function render(initial = '/browse') {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/browse', component: BrowseView }, { path: '/catalog', component: { template: '<div />' } }] });
  await router.push(initial);
  wrapper = mount(BrowseView, { global: { plugins: [router], stubs: { ProductImage: true } } });
  await flushPromises();
  return { router, wrapper: wrapper! };
}
const loads = () => calls.filter(call => call.path.endsWith('/product/loadProduct'));

describe('商城浏览页读取真实 Java 目录', () => {
  it('展示分类导航与在售商品，并按 Java 分页结果说明数量', async () => {
    const { wrapper: view } = await render();
    expect(view.text()).toContain('家居');
    expect(view.text()).toContain('数码');
    expect(view.findAll('.product-tile')).toHaveLength(2);
    expect(view.text()).toContain('共 2 件在售商品');
    expect(loads()).toHaveLength(1);
    expect(loads()[0]!.body).toEqual({ pageNo: '1' });
  });

  it('把店铺范围外的商品 ID 交给 Java 排除', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
      const raw = options.body;
      const body = Object.fromEntries(raw instanceof URLSearchParams ? raw : new URLSearchParams(typeof raw === 'string' ? raw : ''));
      calls.push({ path, body });
      if (path.endsWith('/session')) return json(session.value);
      if (path.endsWith('/catalog/scope')) return json({ include: null, exclude: ['930000000081301'] });
      if (path.endsWith('/traffic/landing')) return json({ recorded: true });
      if (path.endsWith('/product/loadCategory')) return json({ code: 200, data: [] });
      if (path.endsWith('/product/loadProduct')) return json({ code: 200, data: page });
      throw new Error(`Unexpected request: ${path}`);
    }));
    await render();
    expect(loads()[0]!.body.excludeProductIds).toBe('930000000081301');
  });

  it('目录浏览不是推荐曝光，因此不上报任何触点', async () => {
    await render();
    expect(calls.some(call => call.path.includes('/recommendations'))).toBe(false);
    expect(calls.some(call => call.path.includes('/exposures') || call.path.includes('/clicks'))).toBe(false);
  });

  it('关键词与分类进入 Java 查询参数，空关键词不发送该字段', async () => {
    const { router, wrapper: view } = await render();
    await view.get('.browse-search input').setValue('  键盘  ');
    await view.get('.browse-search').trigger('submit');
    await flushPromises();
    expect(router.currentRoute.value.query.keyword).toBe('键盘');
    expect(loads().at(-1)!.body).toEqual({ pageNo: '1', keyword: '键盘' });
    await view.findAll('.category-nav button')[2]!.trigger('click');
    await flushPromises();
    expect(loads().at(-1)!.body).toEqual({ pageNo: '1', keyword: '键盘', categoryId: 'digital' });
    await router.push('/browse');
    await flushPromises();
    expect(loads().at(-1)!.body).toEqual({ pageNo: '1' });
  });

  it('手改链接里的非法价格被拒绝而不是转给 Java', async () => {
    // A number input cannot hold 'abc', so this only arrives through an edited link.
    const { wrapper: view } = await render('/browse?priceFrom=abc');
    expect(view.text()).toContain('价格需为非负金额');
    expect(loads()).toHaveLength(0);
  });

  it('价格区间被校验后才发送，矛盾区间不发请求', async () => {
    const { wrapper: view } = await render();
    const inputs = view.findAll('.browse-search input');
    await inputs[1]!.setValue('50');
    await inputs[2]!.setValue('10');
    await view.get('.browse-search').trigger('submit');
    await flushPromises();
    expect(view.text()).toContain('最低价不能高于最高价');
    await inputs[2]!.setValue('90');
    await view.get('.browse-search select').setValue('PRICE:ASC');
    await view.get('.browse-search').trigger('submit');
    await flushPromises();
    expect(loads().at(-1)!.body).toEqual({ pageNo: '1', priceFrom: '50', priceTo: '90', sortKey: 'PRICE', sortDirection: 'ASC' });
  });

  it('筛选状态进入 URL，因此可直接分享并驱动重新加载', async () => {
    const { router, wrapper: view } = await render();
    await view.findAll('.browse-search input')[1]!.setValue('30');
    await view.get('.browse-search').trigger('submit');
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ priceFrom: '30' });
    // Arriving at the same link reproduces the same Java query without touching the form.
    const { wrapper: shared } = await render('/browse?priceFrom=30&sort=SALE:DESC');
    expect(loads().at(-1)!.body).toEqual({ pageNo: '1', priceFrom: '30', sortKey: 'SALE', sortDirection: 'DESC' });
    expect((shared.get('.browse-search select').element as HTMLSelectElement).value).toBe('SALE:DESC');
  });

  it('无效排序参数被拒绝而不是原样转给 Java', async () => {
    const { wrapper: view } = await render('/browse?sort=DROP:TABLE');
    expect(view.text()).toContain('排序方式无效');
    expect(loads()).toHaveLength(0);
  });

  it('翻页沿用当前筛选，改筛选回到第一页，点击商品进入真实商品详情', async () => {
    page = { list: [product('p1', '陶瓷杯')], totalCount: 12, pageTotal: 3 };
    const { router, wrapper: view } = await render('/browse?keyword=杯');
    await view.findAll('.browse-pager button')[1]!.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ keyword: '杯', page: '2' });
    expect(loads().at(-1)!.body).toEqual({ pageNo: '2', keyword: '杯' });
    await view.findAll('.category-nav button')[1]!.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ keyword: '杯', category: 'home' });
    expect(loads().at(-1)!.body).toEqual({ pageNo: '1', keyword: '杯', categoryId: 'home' });
    await view.get('.product-link').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe('/catalog?product=p1');
  });

  it('空结果说明没有匹配项，而不是显示旧列表', async () => {
    page = { list: [], totalCount: 0, pageTotal: 1 };
    const { wrapper: view } = await render('/browse?keyword=不存在的商品');
    expect(view.findAll('.product-tile')).toHaveLength(0);
    expect(view.text()).toContain('没有匹配“不存在的商品”的在售商品');
  });
});
