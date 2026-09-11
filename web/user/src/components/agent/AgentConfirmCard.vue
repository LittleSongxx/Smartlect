<template>
  <section class="action-confirm-card" :class="{ failed: card.status === 'FAILED' }" aria-label="交易确认卡">
    <header class="card-head"><p class="card-title">{{ title }}</p><span class="card-badge">{{ label }}</span></header>
    <p class="card-hint">请核对以下内容。确认仅适用于本卡所列操作。</p>
    <ul v-if="displayItems.length" class="item-list">
      <li v-for="item in displayItems" :key="item.orderItemId || item.productId + item.propertyValueIds" class="item-row">
        <div class="item-info"><p class="item-name">{{ itemName(item) }}</p><p class="item-sku">{{ itemSku(item) }} × {{ item.buyCount }}</p></div>
      </li>
    </ul>
    <dl class="detail-list">
      <div v-if="card.parameters.addressId" class="detail-row"><dt>收货信息</dt><dd>{{ addressLabel(addresses, card.parameters.addressId) }}</dd></div>
      <div v-for="row in details" :key="row.label" class="detail-row"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
      <div v-if="card.quote_total_cents != null" class="detail-row"><dt>确认总额</dt><dd>{{ money(card.quote_total_cents) }}</dd></div>
      <div v-if="card.parameters.refundAmountCents != null" class="detail-row"><dt>退款金额</dt><dd>{{ money(card.parameters.refundAmountCents) }}</dd></div>
      <div class="detail-row"><dt>有效期至</dt><dd>{{ localDateTime(card.expires_at) }}</dd></div>
    </dl>
    <p v-if="displayLoading" class="card-hint" role="status">正在核对交易对象…</p>
    <p v-else-if="!displayReady" class="risk-tip" role="status">交易对象信息待核对，请重试加载后再确认。<button type="button" class="display-refresh" @click="displayRefresh++">重新核对信息</button></p>
    <p v-if="card.receipt?.error" class="risk-tip">{{ errorText(new Error(card.receipt.error)) }}</p>
    <p v-if="error" class="result-msg error" role="alert">{{ error }}</p>
    <p class="status-label" role="status">{{ label }}</p>
    <button v-if="expired || card.status === 'EXPIRED'" type="button" class="payment-link" @click="reconsultExpired">重新咨询并生成提案 →</button>
    <p v-if="handoff" class="risk-tip">本会话正在人工处理中，暂不能确认交易。</p>
    <footer v-if="card.status === 'PROPOSED'" class="actions">
      <button type="button" class="btn-cancel" :disabled="loading || Boolean(handoff) || expired" @click="decide(false)">拒绝</button>
      <button type="button" class="btn-confirm" :disabled="loading || Boolean(handoff) || !displayReady || expired" @click="decide(true)">{{ loading ? '正在提交…' : '确认' + title }}</button>
    </footer>
    <footer v-else-if="['CONFIRMED', 'EXECUTING', 'UNKNOWN'].includes(card.status)" class="actions">
      <button type="button" class="btn-cancel" :disabled="loading" @click="refresh">刷新状态</button>
      <button type="button" class="btn-confirm" :disabled="loading || Boolean(handoff)" @click="decide(true)">继续核对原操作</button>
    </footer>
    <RouterLink v-if="card.action_type === 'order' && card.status === 'SUCCEEDED'" class="payment-link" to="/orders">前往我的订单，确认模拟付款 →</RouterLink>
  </section>
</template>
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { aiGet, aiPost, errorText, javaGet, javaPost, ownerKey, session, type Proposal, type Run } from '@/api/client';
import { decisionVersion, localDateTime, money, proposalExpired, proposalLabel } from '@/utils/assistant';
import { useAgentSession } from '@/composables/useAgentSession';
import { useOpenAgent } from '@/composables/useOpenAgent';
import { addressLabel, productName, skuLabel } from '@/utils/productDisplay';
const props = defineProps<{ card: Proposal }>();
const emit = defineEmits<{ updated: [proposal: Proposal] }>();
const loading = ref(false);
const { handoff } = useAgentSession();
const { openAgent } = useOpenAgent();
const error = ref('');
const title = computed(() => ({ order: '下单', cancel: '取消订单', refund: '申请退款' })[props.card.action_type]);
const reconsultExpired = () => {
  openAgent({
    draft: `原${title.value}提案 ${props.card.proposal_id} 已过期，请重新核对交易对象和金额并生成新的提案。`
  });
};
const now = ref(Date.now());
const expired = computed(() => proposalExpired(props.card, now.value));
const label = computed(() => expired.value ? '提案已过期或有效期未核实，请重新生成并确认' : proposalLabel(props.card));
let expiryTimer: number | undefined;
watch(() => [props.card.status, props.card.expires_at], () => {
  window.clearTimeout(expiryTimer); now.value = Date.now();
  const remaining = Date.parse(props.card.expires_at) - now.value;
  if (props.card.status === 'PROPOSED' && Number.isFinite(remaining) && remaining > 0) {
    expiryTimer = window.setTimeout(() => { now.value = Date.now(); }, Math.min(remaining + 10, 2147483647));
  }
}, { immediate: true });
onUnmounted(() => window.clearTimeout(expiryTimer));
const details = computed(() => props.card.parameters.reason ? [{ label: '原因', value: props.card.parameters.reason }] : []);
const productDetails = ref<Record<string, Record<string, any>>>({});
const orderItems = ref<Record<string, any>[]>([]);
const displayItems = computed<Record<string, any>[]>(() => props.card.action_type === 'order' ? props.card.parameters.orderList || [] : orderItems.value);
const itemName = (item: Record<string, any>) => props.card.action_type === 'order' ? productName(productDetails.value[item.productId], item.productId) :
  typeof item.productName === 'string' && item.productName.trim() ? item.productName.trim() : '商品名称待核对';
const itemSku = (item: Record<string, any>) => props.card.action_type === 'order' ? skuLabel(productDetails.value[item.productId], item.propertyValueIds) :
  typeof item.propertyInfo === 'string' && item.propertyInfo.trim() ? item.propertyInfo.trim() : '规格名称待核对';
const addresses = ref<Record<string, any>[]>([]);
const displayLoading = ref(false); const displayRefresh = ref(0);
const owner = computed(() => session.value ? ownerKey(session.value.actor) : '');
const displayReady = computed(() => !displayLoading.value && displayItems.value.length > 0 &&
  (props.card.action_type !== 'order' || addressLabel(addresses.value, props.card.parameters.addressId) !== '收货信息待核对') &&
  displayItems.value.every((item) => itemName(item) !== '商品名称待核对' && itemSku(item) !== '规格名称待核对'));
watch(() => [props.card.proposal_id, owner.value, displayRefresh.value], async (_, __, cleanup) => {
  let active = true; cleanup(() => { active = false; });
  productDetails.value = {}; addresses.value = []; orderItems.value = []; displayLoading.value = false;
  if (session.value?.actor.subject_type !== 'user') return;
  const requestedOwner = owner.value;
  if (props.card.action_type !== 'order') {
    displayLoading.value = true;
    try {
      const { order } = await aiGet(`/proposals/${props.card.proposal_id}/display`);
      if (!active || requestedOwner !== owner.value || !Array.isArray(order?.items)) return;
      if (props.card.action_type === 'refund') orderItems.value = order.items.filter((item: Record<string, any>) =>
        item.orderItemId === props.card.parameters.orderItemId && item.orderId === order.orderId);
      else if (order.orderId === props.card.parameters.orderId) orderItems.value = order.items.filter((item: Record<string, any>) => item.orderId === order.orderId);
    } catch { /* Keep the original identifiers visible and leave the new confirmation disabled. */ }
    finally { if (active && requestedOwner === owner.value) displayLoading.value = false; }
    return;
  }
  const ids: string[] = [...new Set<string>((props.card.parameters.orderList || []).map((item: Record<string, any>) => item.productId))];
  displayLoading.value = true;
  const results = await Promise.allSettled([javaGet('/userAddress/loadDataList'), ...ids.map((productId) => javaPost('/product/getProduct', { productId }))]);
  if (!active || requestedOwner !== owner.value) return;
  const addressResult = results[0];
  if (addressResult?.status === 'fulfilled' && Array.isArray(addressResult.value)) addresses.value = addressResult.value;
  ids.forEach((id, index) => {
    const result = results[index + 1];
    if (result?.status === 'fulfilled' && result.value?.productInfo?.productId === id) productDetails.value[id] = result.value;
  });
  displayLoading.value = false;
}, { immediate: true });
async function refresh() {
  if (loading.value) return;
  loading.value = true;
  try { emit('updated', await aiGet<Proposal>(`/proposals/${props.card.proposal_id}`)); }
  catch (reason) { error.value = errorText(reason); }
  finally { loading.value = false; }
}
async function decide(approved: boolean) {
  if (loading.value || handoff.value || expired.value || proposalExpired(props.card) || (approved && props.card.status === 'PROPOSED' && !displayReady.value)) return;
  loading.value = true; error.value = '';
  try {
    const result = await aiPost<Run | { proposal: Proposal }>(`/proposals/${props.card.proposal_id}/confirm`, {
      proposal_version: decisionVersion(props.card), approved,
    });
    const proposal = 'proposal' in result ? result.proposal : result.result?.proposal;
    if (proposal) emit('updated', proposal);
  } catch (reason) {
    error.value = errorText(reason);
    // A lost HTTP response cannot turn an accepted action into a failed transaction.
    try { emit('updated', await aiGet<Proposal>(`/proposals/${props.card.proposal_id}`)); } catch { /* retain the visible original proposal */ }
  } finally { loading.value = false; }
}
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.action-confirm-card {
  width: 100%;
  min-width: 240px;
  max-width: 100%;
  padding: 20px;
  border-radius: 18px;
  border: 1px solid rgba($color-primary, 0.22);
  background: $color-card;
  box-sizing: border-box;
  box-shadow: $shadow-xs;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.card-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  font-family: $font-display;
  color: $color-text-title;
}

.card-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.4;
  color: $color-primary;
  background: rgba($color-primary, 0.1);
}

.card-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.45;
  color: $color-text-muted;
}

.display-refresh { margin-left: 8px; padding: 4px 7px; font-size: 11px; }

.order-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  min-width: 0;
}

.order-id {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  line-height: 1.35;
  color: $color-text-muted;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-amount {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: $color-primary;
}

.item-list {
  list-style: none;
  margin: 0 0 10px;
  padding: 8px;
  border-radius: 8px;
  background: $color-bg-subtle;
}

.item-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;

  & + & {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed rgba($color-text-muted, 0.2);
  }
}

.item-cover {
  flex-shrink: 0;
  width: 52px;
  height: 52px;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;

  &.is-coupon {
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, rgba($color-primary, 0.12), rgba($color-price, 0.1));

    .coupon-icon {
      font-size: 28px;
      color: $color-primary;
    }
  }
}

.item-info {
  flex: 1;
  min-width: 0;
}

.item-name {
  margin: 0;
  font-size: 13px;
  line-height: 1.4;
  font-weight: 500;
  color: $color-text-title;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-sku {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.35;
  color: $color-text-muted;
}

.item-id {
  margin: 4px 0 0;
  font-size: 10px;
  line-height: 1.35;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: $color-text-muted;
  word-break: break-all;
}

.item-meta {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.35;
  color: $color-text-body;
}

.detail-list {
  margin: 0 0 10px;
  padding: 10px;
  border-radius: 8px;
  background: $color-bg-subtle;
}

.detail-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
  font-size: 13px;
  line-height: 1.45;

  & + & {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed rgba($color-text-muted, 0.25);
  }
}

.detail-row dt {
  margin: 0;
  color: $color-text-muted;
  word-break: keep-all;
}

.detail-row dd {
  margin: 0;
  color: $color-text-title;
  font-weight: 500;
  word-break: break-all;
}

.summary-fallback {
  margin: 0 0 10px;
  padding: 10px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.45;
  color: $color-text-title;
  background: $color-bg-subtle;
}

.risk-tip {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.4;
  color: #b45309;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid rgba($color-text-muted, 0.15);
}

.payment-link {
  display: block;
  margin-top: 16px;
  padding: 0;
  border: 0;
  background: transparent;
  font: inherit;
  font-size: 13px;
  color: inherit;
  text-align: left;
  cursor: pointer;
  text-decoration: none;
}

.btn-cancel,
.btn-confirm {
  border: none;
  border-radius: 999px;
  min-width: 88px;
  padding: 9px 18px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.btn-cancel {
  background: $color-bg-subtle;
  color: $color-text-body;

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.btn-confirm {
  background: $color-primary;
  color: #fff;

  &:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }
}

.result-msg {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.45;

  &.success {
    color: #16a34a;
  }

  &.error {
    color: #dc2626;
  }
}

.status-label {
  margin: 0;
  padding-top: 8px;
  font-size: 12px;
  color: $color-text-muted;
  border-top: 1px solid rgba($color-text-muted, 0.15);
}

.is-confirmed {
  border-color: rgba(#16a34a, 0.35);
}

.is-cancelled,
.is-failed,
.is-expired {
  border-color: rgba($color-text-muted, 0.3);
  opacity: 0.92;
}

.is-executing {
  border-color: rgba($color-primary, 0.4);
}

.is-manual-review {
  border-color: rgba(#b45309, 0.45);
}
</style>
