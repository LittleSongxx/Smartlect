<template>
  <section class="page"><header class="page-heading"><div><p class="eyebrow">YOUR ORDERS</p><h1>您的订单</h1><p class="muted">查看订单事实，确认模拟付款或申请售后。金额与状态以服务端回执为准。</p></div><button type="button" :disabled="busy" @click="load">刷新订单</button></header>
    <p v-if="!session" class="panel muted" role="status">正在核对登录状态…</p>
    <p v-else-if="session.actor.subject_type !== 'user'" class="panel">请先<RouterLink :to="loginTo">登录</RouterLink>查看本人订单。</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <div v-for="order in orders" :key="order.orderId" class="panel order-panel">
      <AgentOrderList :list="[order]" /><OrderAmountSummary :order="order" pay-label="订单金额" />
      <div class="actions-inline">
        <button v-if="order.orderStatus === 0" type="button" class="primary" :disabled="busy" @click="preparePayment(order)">查看模拟付款</button>
        <button v-if="order.orderStatus === 0" type="button" :disabled="busy" @click="action('cancel', { orderId: order.orderId })">申请取消订单</button>
        <button v-for="item in refundableItems(order)" :key="item.orderItemId" type="button" :disabled="busy"
          @click="action('refund', { orderItemId: item.orderItemId, refundAmountCents: remainingRefundCents(item) })">
          申请全额退款{{ item.productName ? `（${item.productName}）` : '' }}</button>
        <button v-if="order.orderStatus !== 0" type="button" :disabled="busy" @click="consult(order.orderId)">咨询订单或退款</button>
      </div>
      <small class="muted">创建时间 {{ order.orderTime }} · 支付单 {{ order.payOrderId }}</small>
    </div>
    <p v-if="session?.actor.subject_type === 'user' && !orders.length && !busy" class="panel muted">当前还没有订单，先去选件喜欢的商品吧。</p>
    <div v-if="orders.length" class="pagination"><button type="button" :disabled="busy || page === 1" @click="page--; load()">上一页</button><span>第 {{ page }} 页</span><button type="button" :disabled="busy || page >= pageTotal" @click="page++; load()">下一页</button></div>
    <dialog ref="paymentDialog" aria-labelledby="payment-title" @close="payment = null">
      <section v-if="payment" class="payment-sheet"><h2 id="payment-title">确认模拟付款</h2><p>支付单 {{ payment.payOrderId }}</p>
        <p class="payment-amount">{{ money(payment.amount_cents) }}</p><p>这是智选商城模拟支付，不会扣除真实资金。</p>
        <p v-if="paymentStatus" role="status">{{ paymentStatus }}</p>
        <p v-if="paymentError" class="notice error" role="alert">{{ paymentError }}</p>
        <div class="actions-inline"><button type="button" :disabled="busy" @click="paymentDialog?.close()">关闭</button>
          <button class="primary" type="button" :disabled="busy || paymentDone || !Number.isSafeInteger(payment.amount_cents) || payment.amount_cents < 0" @click="completePayment">{{ busy ? '正在核对…' : '确认支付 ' + money(payment.amount_cents) }}</button></div>
      </section>
    </dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import AgentOrderList from '@/components/agent/AgentOrderList.vue';
import OrderAmountSummary from '@/components/business/OrderAmountSummary.vue';
import { aiGet, aiPost, errorText, javaPost, ownerKey, session } from '@/api/client';
import { money } from '@/utils/assistant';
import { loginTarget } from '@/utils/navigation';
import { orderAllowsRefund, remainingRefundCents } from '@/utils/orderRefund';
import { useAgentSession } from '@/composables/useAgentSession';
import { useOpenAgent } from '@/composables/useOpenAgent';
const orders = ref<Record<string, any>[]>([]); const details = ref<Record<string, any>>({});
const page = ref(1); const pageTotal = ref(1); const busy = ref(false);
const error = ref(''); const message = ref(''); const route = useRoute();
const loginTo = computed(() => loginTarget(route.path, route.fullPath));
const { propose } = useAgentSession();
const { openAgent } = useOpenAgent();
const paymentDialog = ref<HTMLDialogElement>(); const payment = ref<Record<string, any> | null>(null);
const paymentStatus = ref(''); const paymentError = ref(''); const paymentDone = ref(false);
const currentOwner = computed(() => session.value ? ownerKey(session.value.actor) : '');
async function load() {
  if (session.value?.actor.subject_type !== 'user') { orders.value = []; return; }
  const owner = currentOwner.value; busy.value = true; error.value = '';
  try { const data = await javaPost('/order/loadMyOrder', { pageNo: page.value }); if (owner !== currentOwner.value) return;
    orders.value = data.list || []; pageTotal.value = data.pageTotal || 1;
    const loaded: Record<string, any> = {};
    await Promise.all(orders.value.filter(orderAllowsRefund).map(async (order) => {
      try { loaded[order.orderId] = await javaPost('/order/getMyOrderDetail', { orderId: order.orderId }); }
      catch { loaded[order.orderId] = null; }
    }));
    if (owner === currentOwner.value) details.value = loaded;
  } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
function refundableItems(order: Record<string, any>) {
  if (!orderAllowsRefund(order)) return [];
  const items = details.value[order.orderId]?.orderItemList;
  return Array.isArray(items) ? items.filter((item: Record<string, any>) => remainingRefundCents(item) > 0) : [];
}
async function action(kind: string, params: Record<string, any>) {
  if (busy.value) return; busy.value = true;
  try { await propose(kind, params); openAgent(); } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
function consult(orderId: string) { openAgent({ draft: `请查询订单 ${orderId} 的状态和可退款明细` }); }
async function preparePayment(order: Record<string, any>) {
  const owner = currentOwner.value;
  busy.value = true; error.value = ''; paymentError.value = ''; paymentStatus.value = ''; paymentDone.value = false;
  try {
    const result = await aiGet(`/payments/${order.payOrderId}`);
    if (owner !== currentOwner.value) return;
    payment.value = { ...result, payOrderId: order.payOrderId };
    await nextTick(); paymentDialog.value?.showModal();
  } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
async function completePayment() {
  if (busy.value || !payment.value || paymentDone.value) return;
  busy.value = true; paymentError.value = '';
  try {
    const result = await aiPost(`/payments/${payment.value.payOrderId}/complete`, { expected_amount_cents: payment.value.amount_cents });
    paymentDone.value = result.commandStatus === 'business_completed';
    paymentStatus.value = paymentDone.value ? '模拟付款已完成，订单状态已核对。' : '付款已受理，订单状态待核对。请刷新订单查看。';
    await load();
    if (paymentDone.value) paymentDialog.value?.close();
  } catch (reason) { paymentError.value = errorText(reason); }
  finally { busy.value = false; }
}
watch(currentOwner, () => { orders.value = []; details.value = {}; payment.value = null; paymentDialog.value?.close(); page.value = 1; void load(); }, { immediate: true });
</script>
