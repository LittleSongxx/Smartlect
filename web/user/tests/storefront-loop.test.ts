import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { JSDOM } from 'jsdom';
import AgentSendPanel from '../src/views/agent/AgentSendPanel.vue';
import AddressFormPanel from '../src/components/business/AddressFormPanel.vue';
import AddressFormFields from '../src/components/business/AddressFormFields.vue';
import CatalogView from '../src/views/CatalogView.vue';
import LoginView from '../src/views/LoginView.vue';
import { errorText, session } from '../src/api/client';
import { addressApi } from '../src/api/modules';
import { useAgentSession } from '../src/composables/useAgentSession';
import { loginTarget, safeNext } from '../src/utils/navigation';
import { canPurchase, coverUrl, stockCap, uniqueCategories } from '../src/utils/productDisplay';
import { clearProductScopeCache, inProductScope } from '../src/utils/productScope';
import { orderAllowsRefund, remainingRefundCents, yuanToCents } from '../src/utils/orderRefund';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const visitor = { actor: { actor_id: 'v1', subject_type: 'visitor' as const, session_id: 's1', execution_scope_id: 'store' }, csrf_token: 'csrf' };
const user = { actor: { actor_id: 'u1', subject_type: 'user' as const, session_id: 's1', execution_scope_id: 'store' }, csrf_token: 'csrf' };
let wrapper: VueWrapper | undefined;
let calls: { path: string; body: any; method?: string }[];

beforeEach(() => {
  setActivePinia(createPinia());
  clearProductScopeCache();
  calls = [];
  useAgentSession().reset();
  session.value = visitor;
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function bodyOf(options: RequestInit = {}) {
  const raw = options.body;
  if (raw instanceof URLSearchParams) return Object.fromEntries(raw);
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return Object.fromEntries(new URLSearchParams(raw)); }
  }
  return {};
}

describe('封面、库存与登录回跳', () => {
  it('把 Java 文件名编成文件接口，已是 /api/file/ 的原样使用', () => {
    expect(coverUrl('')).toBe('');
    expect(coverUrl('../secret')).toBe('');
    expect(coverUrl('/api/file/getResource?sourceName=a.jpg')).toBe('/api/file/getResource?sourceName=a.jpg');
    expect(coverUrl('a.jpg,b.jpg')).toBe('/api/file/getResource?sourceName=a.jpg');
    expect(coverUrl('folder/a.jpg')).toBe('/api/file/getResource?sourceName=folder%2Fa.jpg');
    expect(stockCap(0)).toBe(0);
    expect(stockCap(3)).toBe(3);
    expect(stockCap(null)).toBe(0);
    expect(canPurchase({ subjectType: 'user', addressId: 'a1', selected: { stock: 2 }, quantity: 3 })).toBe(false);
    expect(canPurchase({ subjectType: 'user', addressId: 'a1', selected: { stock: 2 }, quantity: 2 })).toBe(true);
    expect(canPurchase({ subjectType: 'user', addressId: 'a1', selected: { stock: 0 }, quantity: 1 })).toBe(false);
    expect(safeNext('https://evil.example/x')).toBe('/');
    expect(safeNext('//evil.example')).toBe('/');
    expect(safeNext('/login?next=/orders')).toBe('/');
    expect(safeNext('/catalog?product=p1')).toBe('/catalog?product=p1');
    expect(safeNext('/catalog?product=p1&sku=s1')).toBe('/catalog?product=p1&sku=s1');
    expect(loginTarget('/catalog', '/catalog?product=p1')).toBe(`/login?next=${encodeURIComponent('/catalog?product=p1')}`);
    expect(loginTarget('/catalog', '/catalog?product=p1&sku=s1')).toBe(`/login?next=${encodeURIComponent('/catalog?product=p1&sku=s1')}`);
    expect(uniqueCategories([
      { categoryId: 'S90', categoryName: '数码' },
      { categoryId: '90', categoryName: '数码' },
      { categoryId: '91', categoryName: '家居' },
      { categoryId: 'S91', categoryName: '家居' },
    ]).map((row) => row.categoryId)).toEqual(['90', '91']);
    expect(uniqueCategories([
      { categoryId: '90', categoryName: '数码' },
      { categoryId: '10001', categoryName: '数码' },
    ]).map((row) => row.categoryId)).toEqual(['10001']);
    expect(errorText(new Error('product_scope_denied'))).toBe('该商品不在当前店铺可售范围内，请换一件再下单。');
    expect(inProductScope('910000000000000', { include: null, exclude: [] })).toBe(false);
    expect(inProductScope('917186661226040', { include: null, exclude: [] })).toBe(true);
    expect(inProductScope('930000000081301', { include: null, exclude: [] })).toBe(false);
    expect(inProductScope('930000000081301', { include: ['930000000081301'], exclude: [] })).toBe(true);
  });

  it('同商品换规格只更新选中规格，不重拉详情', async () => {
    let products = 0;
    vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
      calls.push({ path, body: bodyOf(options) });
      if (path.endsWith('/session')) return json(session.value);
      if (path.endsWith('/catalog/scope')) return json({ include: null, exclude: [] });
      if (path.endsWith('/traffic/landing')) return json({ recorded: true });
      if (path.endsWith('/product/getProduct')) {
        products += 1;
        return json({ code: 200, data: { productInfo: { productId: 'p1', productName: '商品' }, skuList: [
          { propertyValueIds: 'sku1', price: 10, stock: 2 }, { propertyValueIds: 'sku2', price: 12, stock: 5 }] } });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/catalog', component: CatalogView }, { path: '/login', component: { template: '<div />' } }] });
    await router.push('/catalog?product=p1&sku=sku1'); await router.isReady();
    wrapper = mount(CatalogView, { global: { plugins: [router], stubs: { ProductImage: true } } }); await flushPromises();
    expect(wrapper.text()).toContain('库存 2'); expect(products).toBe(1);
    await router.replace({ path: '/catalog', query: { product: 'p1', sku: 'sku2' } }); await flushPromises();
    expect(wrapper.get('.sku-options button.selected').text()).toContain('库存 5');
    expect(products).toBe(1);
  });

  it('超库存不能生成确认卡，库存为 0 时数量上限为 0', async () => {
    session.value = user;
    vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
      calls.push({ path, body: bodyOf(options) });
      if (path.endsWith('/session')) return json(session.value);
      if (path.endsWith('/catalog/scope')) return json({ include: null, exclude: [] });
      if (path.endsWith('/traffic/landing')) return json({ recorded: true });
      if (path.endsWith('/product/getProduct')) return json({ code: 200, data: { productInfo: { productId: 'p1', productName: '商品' }, skuList: [{ propertyValueIds: 'sku1', price: 10, stock: 2 }] } });
      if (path.endsWith('/userAddress/loadDataList')) return json({ code: 200, data: [{ addressId: 'a1', addressee: '张三', address: '路1号' }] });
      if (path.endsWith('/discountCoupon/loadUserCoupon')) return json({ code: 200, data: { list: [{ userCouponId: 'uc1', couponName: '满减券', thresholdAmount: 20 }] } });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/catalog', component: CatalogView }] });
    await router.push('/catalog?product=p1&sku=sku1'); await router.isReady();
    wrapper = mount(CatalogView, { global: { plugins: [router], stubs: { ProductImage: true, RouterLink: true } } }); await flushPromises();
    const qty = wrapper.get('.purchase-fields input[type=number]');
    expect((qty.element as HTMLInputElement).max).toBe('2');
    await qty.setValue(3); await flushPromises();
    expect(wrapper.get<HTMLButtonElement>('button.primary').element.disabled).toBe(true);
    await qty.setValue(2); await flushPromises();
    expect(wrapper.get<HTMLButtonElement>('button.primary').element.disabled).toBe(false);
    expect(wrapper.text()).toContain('满减券');
  });

  it('登录成功后回到 next，默认回商城首页', async () => {
    let loggedIn = false;
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.endsWith('/account/checkCode')) return json({ code: 200, data: { checkCodeKey: 'captcha1', checkCode: 'data:image/png;base64,' } });
      if (path.endsWith('/account/login')) { loggedIn = true; return json({ code: 200, data: {} }); }
      if (path.endsWith('/session')) return json({ actor: loggedIn ? user.actor : visitor.actor, csrf_token: 'csrf' });
      if (path.endsWith('/traffic/bind')) return json({ bound: true, conversation_ids: [], assignment_conflict: false });
      return json([]);
    }));
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/login', component: LoginView }, { path: '/assistant', component: { template: '<div />' } },
      { path: '/forgot-password', component: { template: '<div />' } },
      { path: '/catalog', component: { template: '<div />' } }] });
    await router.push('/login?next=/catalog?product=p1'); await router.isReady();
    wrapper = mount(LoginView, { global: { plugins: [router] } }); await flushPromises();
    await wrapper.get('input[type=email]').setValue('synthetic@example.invalid');
    await wrapper.get('input[type=password]').setValue('Abcd1234');
    await wrapper.get('form').trigger('submit'); await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe('/catalog?product=p1');
  });
});

describe('地址、退款与助手入参', () => {
  it('地址表单提交 Java 字段', async () => {
    session.value = user;
    const addAddress = vi.spyOn(addressApi, 'addAddress').mockResolvedValue(null);
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/address', component: { template: '<div />' } }, { path: '/login', component: { template: '<div />' } }] });
    await router.push('/address'); await router.isReady();
    wrapper = mount(AddressFormPanel, {
      props: { modelValue: true },
      global: { plugins: [router], stubs: { 'el-dialog': { template: '<div><slot /></div>' }, 'el-drawer': { template: '<div><slot /></div>' }, 'el-cascader': true, 'el-button': true, 'el-icon': true, 'el-checkbox': true } }
    });
    await flushPromises();
    const fields = wrapper.findComponent(AddressFormFields);
    // 表单字段由子组件持有同一个 reactive 对象，直接按用户填写的结果赋值
    Object.assign(fields.props('form'), {
      addressee: '张三', phone: '13800000000',
      regionCodes: ['11', '1101', '110101'], detailAddress: '演示路1号', defaultType: 1
    });
    fields.vm.$emit('submit'); await flushPromises();
    expect(addAddress).toHaveBeenCalledWith({
      addressee: '张三', phone: '13800000000', address: '北京市东城区演示路1号', defaultType: 1
    });
  });


  it('助手发送带上详情页 product_id 与 sku_key', async () => {
    session.value = user;
    vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
      calls.push({ path, body: typeof options.body === 'string' ? JSON.parse(options.body) : {}, method: options.method });
      if (path.endsWith('/session')) return json(session.value);
      if (path.endsWith('/conversations')) return json({ conversation_id: 'c1' });
      if (path.includes('/messages')) return json({ agent_run_id: 'r1', conversation_id: 'c1', state: 'COMPLETED' });
      if (path.endsWith('/events')) return new Response('');
      if (path.endsWith('/conversations/c1')) return json({ conversation_id: 'c1', messages: [] });
      if (path.endsWith('/runs/r1')) return json({ agent_run_id: 'r1', conversation_id: 'c1', state: 'COMPLETED' });
      return json([]);
    }));
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/assistant', component: AgentSendPanel }] });
    await router.push({ path: '/assistant', query: { product: 'p1', sku: 'sku1', draft: '关于商品' } }); await router.isReady();
    wrapper = mount(AgentSendPanel, { global: { plugins: [router] } }); await flushPromises();
    await wrapper.get('form').trigger('submit'); await flushPromises();
    const message = calls.find(call => String(call.path).includes('/messages'));
    expect(message?.body).toMatchObject({ text: '关于商品', product_id: 'p1', sku_key: 'sku1', focus_mode: 'PRODUCT' });
  });
});
