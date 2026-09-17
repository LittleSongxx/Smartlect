<template>
  <section class="page">
    <header v-if="!detail && !productQuery" class="page-heading"><div><p class="eyebrow">SMARTLECT COLLECTION</p><h1>选一件刚好合适的。</h1><p class="muted">按用途和预算看可售规格，也可以让导购帮您比较后再确认。</p></div><button type="button" :disabled="busy || !session" @click="load">刷新商品</button></header>
    <form v-if="!detail" class="recommendation-search" @submit.prevent="load"><label>用途或商品<input v-model="query" maxlength="200" placeholder="例如日常出行、收纳" /></label><label>最高单价（元）<input v-model="maxPrice" type="number" min="0" step="0.01" placeholder="不限" /></label><button type="submit" class="primary" :disabled="busy || !session">{{ busy ? '正在查询…' : '查看推荐' }}</button></form>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <AgentProductList v-if="!detail" :list="products" @select="select" />
    <section v-if="detail" class="panel product-detail" aria-label="商品规格与下单">
      <header class="page-heading"><div><p class="eyebrow">商品详情</p><h2>{{ productName(detail, detail.productInfo.productId) }}</h2></div><button type="button" @click="close">关闭详情</button></header>
      <div class="pdp-layout">
      <div class="detail-media"><ProductImage :product="detail.productInfo" width="100%" height="360" fit="cover" :lazy="false" :use-thumbnail="false" />
        <MarkdownContent v-if="detail.productInfo.productDesc" :content="normalizeProductDesc(detail.productInfo.productDesc)" class="detail-desc" allow-images center-images /></div>
      <div class="pdp-buy">
      <div class="sku-options" role="group" aria-label="选择规格"><button v-for="sku in detail.skuList || []" :key="sku.propertyValueIds" type="button" :class="{ selected: selectedSku === sku.propertyValueIds }" :disabled="sku.stock === 0" @click="chooseSku(sku.propertyValueIds)">
        {{ skuLabel(detail, sku.propertyValueIds) }} · ¥{{ Number(sku.price).toFixed(2) }} · {{ sku.stock == null ? '库存待核实' : `库存 ${sku.stock}` }}</button></div>
      <p v-if="!detail.skuList?.length" class="muted">该商品暂无可购买规格。</p>
      <div class="purchase-fields"><label>数量<input v-model.number="quantity" type="number" min="1" :max="quantityMax" step="1" /></label>
        <label>收货地址<select v-model="addressId"><option value="">请选择本人收货地址</option><option v-for="address in addresses" :key="address.addressId" :value="address.addressId">{{ addressLabel(addresses, address.addressId) }}</option></select></label>
        <label v-if="coupons.length">优惠券<select v-model="userCouponId"><option value="">不使用优惠券</option><option v-for="coupon in coupons" :key="coupon.userCouponId" :value="coupon.userCouponId">{{ couponLabel(coupon) }}</option></select></label></div>
      <p v-if="!scoped" class="notice error" role="alert">该商品不在当前店铺可售范围内，请换一件再下单。</p>
      <p v-else-if="authStore.isTrial" class="muted">作品集试用账号只能浏览，不能下单。</p>
      <p v-else-if="session?.actor.subject_type !== 'user'" class="muted"><RouterLink :to="loginTo">登录</RouterLink>后可生成下单确认卡。</p>
      <p v-else-if="!addresses.length" class="muted">当前账号暂无收货地址，请先<RouterLink :to="{ path: '/address', query: { next: route.fullPath, action: 'add' } }">添加收货地址</RouterLink>后再下单。</p>
      <div class="actions-inline"><button class="primary" type="button" :disabled="busy || !canBuy" @click="buy">生成下单确认卡</button><button type="button" @click="consult">问问导购</button></div>
      <p class="muted">先核对报价，再由您确认下单。付款需要单独确认。确认卡展示的总额已含所选优惠券。</p>
      <details class="muted"><summary>商品与规格凭据</summary><p>商品编号 {{ detail.productInfo.productId }} · 所选规格编号 {{ selectedSku || '未选择' }} · 地址编号 {{ addressId || '未选择' }}<template v-if="userCouponId"> · 优惠券 {{ userCouponId }}</template></p></details>
      </div>
      </div>
    </section>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AgentProductList from '@/components/agent/AgentProductList.vue';
import MarkdownContent from '@/components/common/MarkdownContent.vue';
import ProductImage from '@/components/common/ProductImage.vue';
import { aiGet, errorText, javaGet, javaPost, ownerKey, session } from '@/api/client';
import { recordLanding, recommendationTouch, type RecommendationList } from '@/api/traffic';
import { useAgentSession } from '@/composables/useAgentSession';
import { useOpenAgent } from '@/composables/useOpenAgent';
import { loginTarget } from '@/utils/navigation';
import { addressLabel, canPurchase, productName, skuLabel, stockCap } from '@/utils/productDisplay';
import { normalizeProductDesc } from '@/utils/productDesc';
import { inProductScope, loadProductScope } from '@/utils/productScope';
import { useAuthStore } from '@/stores/auth';
const authStore = useAuthStore();
const products = ref<Record<string, any>[]>([]); const detail = ref<Record<string, any> | null>(null);
const query = ref(''); const maxPrice = ref(''); const recommendation = ref<RecommendationList | null>(null);
const addresses = ref<Record<string, any>[]>([]); const coupons = ref<Record<string, any>[]>([]);
const selectedSku = ref(''); const quantity = ref(1); const addressId = ref(''); const userCouponId = ref('');
const busy = ref(false); const error = ref(''); const route = useRoute(); const router = useRouter(); const { propose } = useAgentSession();
const { openAgent } = useOpenAgent();
const owner = computed(() => session.value ? ownerKey(session.value.actor) : '');
const selected = computed(() => detail.value?.skuList?.find((sku: Record<string, any>) => sku.propertyValueIds === selectedSku.value));
const quantityMax = computed(() => stockCap(selected.value?.stock));
const scoped = ref(true);
const canBuy = computed(() => scoped.value && canPurchase({
  subjectType: session.value?.actor.subject_type, addressId: addressId.value, selected: selected.value,
  quantity: quantity.value, trial: authStore.isTrial,
}));
const loginTo = computed(() => loginTarget(route.path, route.fullPath));
const productQuery = computed(() => typeof route.query.product === 'string' && route.query.product);
let detailRequest = 0;
let listRequest = 0;
function couponLabel(coupon: Record<string, any>) {
  const name = typeof coupon.couponName === 'string' && coupon.couponName.trim() ? coupon.couponName.trim() : coupon.userCouponId;
  const threshold = coupon.thresholdAmount != null ? ` · 满${coupon.thresholdAmount}` : '';
  return `${name}${threshold}`;
}
function applySkuFromRoute() {
  const sku = route.query.sku;
  if (!detail.value?.skuList) return;
  if (typeof sku === 'string' && sku) {
    const match = detail.value.skuList.find((item: Record<string, any>) => item.propertyValueIds === sku);
    if (match) selectedSku.value = match.propertyValueIds;
  }
}
function chooseSku(ids: string) {
  selectedSku.value = ids;
  const productId = detail.value?.productInfo?.productId;
  if (productId) void router.replace({ path: '/catalog', query: { product: String(productId), sku: ids } });
}
async function load() {
  if (!session.value) return;
  const requestId = ++listRequest; const requestedOwner = owner.value;
  busy.value = true; error.value = ''; products.value = []; recommendation.value = null;
  try {
    const parameters = new URLSearchParams({ query: query.value.trim(), limit: '8' });
    const priceText = String(maxPrice.value).trim();
    if (priceText) {
      if (!/^\d+(\.\d{1,2})?$/.test(priceText)) throw new Error('最高单价需为非负金额，最多两位小数。');
      const [whole, fraction = ''] = priceText.split('.');
      const cents = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
      if (!Number.isSafeInteger(cents) || cents > 100000000) throw new Error('最高单价超出有效范围。');
      parameters.set('max_price_cents', String(cents));
    }
    await recordLanding();
    if (requestId !== listRequest || requestedOwner !== owner.value) return;
    const result = await aiGet<RecommendationList>(`/recommendations?${parameters}`, AbortSignal.timeout(30000));
    if (requestId !== listRequest || requestedOwner !== owner.value) return;
    if (!Array.isArray(result.items) || typeof result.recommendation_id !== 'string' || !result.recommendation_id) throw new Error('推荐列表暂不可用，请稍后刷新。');
    const items = result.items.map((item) => ({ ...item, recommendation_id: result.recommendation_id }));
    if (items.some((item) => !recommendationTouch(item))) throw new Error('推荐列表凭据不完整，请稍后刷新。');
    recommendation.value = result; products.value = items;
  } catch (reason) { if (requestId === listRequest && requestedOwner === owner.value) error.value = errorText(reason); }
  finally { if (requestId === listRequest) busy.value = false; }
}
async function loadDetail(productId: string) {
  const requestedOwner = owner.value;
  const requestId = ++detailRequest;
  busy.value = true; error.value = ''; detail.value = null; selectedSku.value = ''; quantity.value = 1; userCouponId.value = ''; coupons.value = []; scoped.value = true;
  try {
    const product = await javaPost('/product/getProduct', { productId });
    if (requestId !== detailRequest || requestedOwner !== owner.value) return;
    detail.value = product;
    scoped.value = inProductScope(String(product?.productInfo?.productId || productId), await loadProductScope(requestedOwner));
    if (requestId !== detailRequest || requestedOwner !== owner.value) return;
    const match = detail.value?.skuList?.find((sku: Record<string, any>) => sku.propertyValueIds === route.query.sku && sku.stock !== 0);
    selectedSku.value = match?.propertyValueIds || detail.value?.skuList?.find((sku: Record<string, any>) => sku.stock !== 0)?.propertyValueIds || '';
    if (session.value?.actor.subject_type === 'user' && requestedOwner === owner.value) {
      const data = await javaGet('/userAddress/loadDataList');
      if (requestId === detailRequest && requestedOwner === owner.value) { addresses.value = data; addressId.value = addresses.value[0]?.addressId || ''; }
      try {
        const page = await javaPost('/discountCoupon/loadUserCoupon', { pageNo: 1, status: 0 });
        if (requestId === detailRequest && requestedOwner === owner.value) coupons.value = page?.list || [];
      } catch { if (requestId === detailRequest && requestedOwner === owner.value) coupons.value = []; }
    }
  } catch (reason) { if (requestId === detailRequest && requestedOwner === owner.value) error.value = errorText(reason); }
  finally { if (requestId === detailRequest) busy.value = false; }
}
async function select(item: Record<string, any>) { await router.replace({ path: '/catalog', query: { product: String(item.productId), sku: String(item.propertyValueIds || '') } }); }
async function close() { await router.replace('/catalog'); }
async function consult() {
  const info = detail.value?.productInfo;
  const spec = selectedSku.value ? `，规格编号 ${selectedSku.value}` : '';
  openAgent({
    productId: String(info?.productId || ''),
    skuKey: selectedSku.value || '',
    draft: `关于商品「${info?.productName}」（商品编号 ${info?.productId}${spec}），我想了解`,
  });
}
async function buy() {
  if (authStore.isTrial) { error.value = '作品集试用账号只能浏览，不能下单。'; return; }
  if (!canBuy.value || busy.value || !scoped.value) return; busy.value = true; error.value = '';
  try {
    const parameters: Record<string, any> = { payMethod: 'mock', addressId: addressId.value, orderFrom: 0,
      orderList: [{ productId: detail.value!.productInfo.productId, propertyValueIds: selectedSku.value, buyCount: quantity.value }] };
    if (userCouponId.value) parameters.userCouponId = userCouponId.value;
    await propose('order', parameters);
    openAgent();
  } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
watch([owner, () => typeof route.query.product === 'string' ? route.query.product : ''], () => {
  detailRequest++; listRequest++; detail.value = null; addresses.value = []; addressId.value = '';
  coupons.value = []; userCouponId.value = '';
  products.value = []; recommendation.value = null; busy.value = false;
  if (!owner.value) return;
  const id = route.query.product;
  if (typeof id === 'string' && id) void loadDetail(id);
  else void load();
}, { immediate: true });
watch(() => typeof route.query.sku === 'string' ? route.query.sku : '', () => { if (detail.value) applySkuFromRoute(); });
watch(selected, (sku) => {
  const cap = stockCap(sku?.stock);
  if (cap >= 1 && quantity.value > cap) quantity.value = cap;
});
</script>
<style scoped>
.recommendation-search { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 14px; margin-bottom: 22px; padding: 18px; background: #fffdf9; border: 1px solid #e4d9c8; border-radius: 20px; }
.recommendation-search label { flex: 1; min-width: 140px; margin: 0; }
.recommendation-search button { min-height: 44px; }
.pdp-layout { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(280px, 1.15fr); gap: 28px; align-items: start; }
.detail-media { display: grid; gap: 14px; }
.detail-media :deep(.product-image) { width: 100%; border-radius: 18px; background: #efe9df; }
.detail-desc { margin: 0; color: #4d473e; }
.detail-desc :deep(img) { max-width: 100%; height: auto; border-radius: 12px; }
.pdp-buy { min-width: 0; }
@media (max-width: 800px) { .pdp-layout { grid-template-columns: 1fr; } }
</style>
