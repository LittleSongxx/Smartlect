import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import ElementPlus from 'element-plus';
import { createPinia, setActivePinia } from 'pinia';
import { JSDOM } from 'jsdom';
import OrderDetailView from '../src/views/OrderDetailView.vue';
import { orderApi } from '../src/api/modules';
import { useAgentSession } from '../src/composables/useAgentSession';
import { confirmAction } from '../src/utils/confirm';

vi.mock('../src/utils/confirm', () => ({ confirmAction: vi.fn(async () => true) }));
// 页面在 setup 里解构了 propose，事后 spy 拿不到同一个引用，所以整块替换实现
const { proposeSpy } = vi.hoisted(() => ({ proposeSpy: vi.fn(async () => ({})) }));
vi.mock('../src/composables/useAgentSession', async () => {
  const actual = await vi.importActual<typeof import('../src/composables/useAgentSession')>('../src/composables/useAgentSession');
  return { ...actual, useAgentSession: () => ({ ...actual.useAgentSession(), propose: proposeSpy }) };
});

const order = {
  orderId: 'o1',
  orderStatus: 2,
  productAmount: 200,
  orderAmount: 200,
  orderTime: '2026-09-15 10:00:00',
  orderItemList: [
    { orderItemId: 'i1', productName: '陶瓷杯', itemAmount: 120, buyCount: 1, paidAmount: 120, refundedAmount: 20 },
    { orderItemId: 'i2', productName: '帆布袋', itemAmount: 80, buyCount: 1, paidAmount: 80, refundedAmount: 0 },
    { orderItemId: 'i3', productName: '全部退完的书', itemAmount: 30, buyCount: 1, paidAmount: 30, refundedAmount: 30 }
  ]
};

let wrapper: VueWrapper | undefined;

const render = async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/order/:orderId', component: OrderDetailView },
    { path: '/assistant', component: { template: '<div />' } },
    { path: '/product/:productId', component: { template: '<div />' } }
  ] });
  await router.push('/order/o1'); await router.isReady();
  const w = mount(OrderDetailView, { global: { plugins: [router, ElementPlus] } });
  await flushPromises();
  return w;
};

beforeEach(() => {
  setActivePinia(createPinia());
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  vi.spyOn(orderApi, 'getMyOrderDetail').mockResolvedValue(structuredClone(order));
  useAgentSession().reset();
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('订单详情的全额退款入口', () => {
  it('按未退金额汇总，只对还有余额的明细生成退款确认卡', async () => {
    proposeSpy.mockClear();
    wrapper = await render();

    // 120-20 + 80 = 180；已退完的那件不再出现
    const button = wrapper.findAll('button').find((b) => b.text().includes('申请全额退款'));
    expect(button?.text()).toContain('180.00');

    await button!.trigger('click');
    await flushPromises();

    expect(confirmAction).toHaveBeenCalledOnce();
    expect(proposeSpy).toHaveBeenCalledTimes(2);
    expect(proposeSpy).toHaveBeenCalledWith('refund', { orderItemId: 'i1', refundAmountCents: 10000 });
    expect(proposeSpy).toHaveBeenCalledWith('refund', { orderItemId: 'i2', refundAmountCents: 8000 });
  });

  it('订单已关闭时不出现全额退款入口', async () => {
    vi.spyOn(orderApi, 'getMyOrderDetail').mockResolvedValue({ ...structuredClone(order), orderStatus: 5 });
    wrapper = await render();
    expect(wrapper.findAll('button').some((b) => b.text().includes('申请全额退款'))).toBe(false);
  });
});
