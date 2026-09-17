import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import { JSDOM } from 'jsdom';
import CategoryView from '../src/views/CategoryView.vue';
import SearchResultView from '../src/views/SearchResultView.vue';
import PcSearchResultView from '../src/views/pc/PcSearchResultView.vue';
import { productApi } from '../src/api/modules';

// 两个列表页共用 usePagedList：这里锁住"首屏一次请求 + 翻页追加 + 门店范围过滤 + 非法价格不发请求"，
// 重构（把分页机制抽成 composable）不能悄悄改变这些行为。
const product = (id: string, name: string, status = 1) => ({
  productId: id, productName: name, minPrice: 19, cover: '', totalSale: 3, status
});
const categoryPayload = {
  list: [product('p1', '陶瓷杯'), product('p2', '帆布袋'), { productId: 'p3', productName: '下架货', status: 0 }],
  totalCount: 2, pageTotal: 1, pageNo: 1
};
const searchPayload = {
  list: [product('s1', '智能手机')],
  totalCount: 1, pageTotal: 2, pageNo: 1
};

let wrapper: VueWrapper | undefined;
// 用可手动触发的 IntersectionObserver 替身：滚动到底是通过它回到达的，比伸手进组件状态更接近真实路径
let triggerIntersect: (() => void) | null = null;

const mountPage = async (component: any, path: string, query = '') => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/category/:categoryId', component: CategoryView },
    { path: '/search-result', component: SearchResultView },
    { path: '/pc-search-result', component: PcSearchResultView },
    { path: '/product/:productId', component: { template: '<div />' } },
    { path: '/search', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } }
  ] });
  await router.push(path + query); await router.isReady();
  const w = mount(component, { global: { plugins: [router, ElementPlus], stubs: { ProductCard: { props: ['product'], template: '<div class="product-card-stub">{{ product.productName }}</div>' } } } });
  await flushPromises();
  await new Promise((resolve) => setTimeout(resolve, 30));
  await flushPromises();
  return w;
};

beforeEach(() => {
  setActivePinia(createPinia());
  triggerIntersect = null;
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) {
      triggerIntersect = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  vi.stubGlobal('sessionStorage', new JSDOM('', { url: 'http://localhost' }).window.sessionStorage);
  vi.spyOn(productApi, 'loadCategory').mockResolvedValue([
    { categoryId: '10', categoryName: '数码', pCategoryId: '0', children: [] }
  ] as any);
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('分类页：分页列表', () => {
  it('首屏按分类拉一页，下架商品被过滤掉，鼠标改价格不合法时不发请求', async () => {
    const loadProduct = vi.spyOn(productApi, 'loadProduct').mockResolvedValue(categoryPayload as any);
    wrapper = await mountPage(CategoryView, '/category/10');
    expect(loadProduct).toHaveBeenCalledTimes(1);
    expect(loadProduct.mock.calls[0][0]).toMatchObject({ pageNo: 1, categoryId: '10' });
    expect(wrapper.findAll('.product-card-stub')).toHaveLength(2);
    expect(wrapper.text()).toContain('在售 2 件');
    expect(wrapper.text()).not.toContain('下架货');

    const priceInput = wrapper.findAll('input')[0]!;
    await priceInput.setValue('abc');
    await wrapper.find('.filter-apply').trigger('click');
    await flushPromises();
    expect(loadProduct).toHaveBeenCalledTimes(1);   // 非法价格没有再发请求
    // 提示走 ElMessage，挂在 body 上而不是组件里
    expect(document.body.textContent).toContain('价格需为非负金额');
  });
});

describe('搜索结果页：分页列表', () => {
  it('翻页追加而不是替换，页码与总数来自服务端', async () => {
    const search = vi.spyOn(productApi, 'searchProducts')
      .mockResolvedValueOnce(searchPayload as any)
      .mockResolvedValueOnce({ list: [product('s2', '折叠屏手机')], totalCount: 2, pageTotal: 2, pageNo: 2 } as any);
    const globalFetch = vi.fn(async () => new Response(JSON.stringify({ code: 200, data: null }), { status: 200 }));
    vi.stubGlobal('fetch', globalFetch);

    wrapper = await mountPage(SearchResultView, '/search-result', '?q=%E6%89%8B%E6%9C%BA');
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0][0]).toMatchObject({ keyWords: '手机', pageNo: 1 });
    expect(wrapper.findAll('.product-card-stub')).toHaveLength(1);

    // 模拟滚到底：哨兵进入视口触发下一页
    expect(triggerIntersect).toBeTypeOf('function');
    triggerIntersect!();
    await flushPromises();
    expect(search).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll('.product-card-stub').map((n) => n.text())).toEqual(['智能手机', '折叠屏手机']);
  });
});

describe('PC 搜索结果页：与移动端共用同一份查询逻辑', () => {
  it('价格非法时不发请求，正常时按关键词查并渲染商品', async () => {
    const search = vi.spyOn(productApi, 'searchProducts').mockResolvedValue(searchPayload as any);
    wrapper = await mountPage(PcSearchResultView, '/pc-search-result', '?q=%E6%89%8B%E6%9C%BA');
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0][0]).toMatchObject({ keyWords: '手机', pageNo: 1 });
    expect(wrapper.findAll('.pc-product-tile').length).toBeGreaterThan(0);

    // PC 版此前漏掉了价格校验，现在与移动端同一套：非法值在客户端就被拦下
    const priceInput = wrapper.findAll('input')[0]!;
    await priceInput.setValue('abc');
    expect(document.body.textContent).toContain('价格需为非负金额');
    expect(search).toHaveBeenCalledTimes(1);
  });
});
