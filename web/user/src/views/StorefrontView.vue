<template>
  <section class="page storefront">
    <header class="storefront-hero">
      <div><p class="eyebrow">SMARTLECT · 智选商城</p><h1>先了解，再决定。</h1><p>像和店员聊一样挑选日常用品。规格、价格和库存都来自真实商品，下单与付款始终由您确认。</p>
        <div class="actions-inline"><RouterLink class="primary storefront-link" to="/browse">逛全部商品</RouterLink><button type="button" class="storefront-link" @click="openAgent()">让导购帮我选</button></div>
      </div><div class="hero-note"><span>选购 · 咨询 · 售后</span><p>挑选更轻松<br />决定由您确认</p><RouterLink to="/orders">查看我的订单 →</RouterLink></div>
    </header>
    <nav v-if="categories.length" class="storefront-categories" aria-label="商品分类">
      <RouterLink to="/browse">全部分类</RouterLink>
      <RouterLink v-for="item in categories" :key="item.categoryId" :to="{ path: '/browse', query: { category: item.categoryId } }">{{ item.categoryName }}</RouterLink>
    </nav>
    <section aria-labelledby="recommendation-title" class="storefront-section">
      <header class="page-heading"><div><h2 id="recommendation-title">为你推荐</h2><p class="muted">结合您的购物偏好与当前可售规格。<RouterLink to="/preferences">管理偏好</RouterLink></p></div><button type="button" :disabled="busy || !session" @click="load">{{ busy ? '正在更新…' : '看看新推荐' }}</button></header>
      <p v-if="recommendationError" class="notice error" role="alert">{{ recommendationError }}</p>
      <AgentProductList v-else-if="recommendation" :list="products" @select="select" />
      <p v-else class="muted" role="status">{{ busy ? '正在为您查看商品…' : '等待商店连接…' }}</p>
    </section>
    <section aria-labelledby="promotion-title" class="storefront-section">
      <header class="page-heading"><div><h2 id="promotion-title">推广 <span class="ad-label">广告</span></h2><p class="muted">商家推广商品，与上方普通推荐分开展示。本地演示使用模拟广告费用。</p></div></header>
      <div v-if="ads.length" class="promotion-grid"><PromotionCard v-for="item in ads" :key="`${owner}:${revision}:${item.creative_id}`" :item="item" @select="select" @refresh="load" /></div>
      <p v-else class="panel muted" role="status">{{ busy ? '正在查看推广商品…' : '当前没有可展示的推广商品，您可以继续浏览上方推荐。' }}</p>
    </section>
    <aside class="panel storefront-help"><div><h2>还没找到合适的？</h2><p class="muted">告诉导购您的预算与需求，或直接咨询配送、退换货和订单问题。</p></div><button type="button" class="storefront-link" @click="openAgent()">去咨询导购与客服 →</button></aside>
  </section>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import AgentProductList from '@/components/agent/AgentProductList.vue';
import PromotionCard from '@/components/PromotionCard.vue';
import { aiGet, errorText, javaGet, session } from '@/api/client';
import { useOpenAgent } from '@/composables/useOpenAgent';
import { usePromotions } from '@/composables/usePromotions';
import { uniqueCategories } from '@/utils/productDisplay';
import { recordLanding, recommendationTouch, type RecommendationList } from '@/api/traffic';
const router = useRouter();
const { openAgent } = useOpenAgent();
const { ads, owner, revision, load: loadAds } = usePromotions(2);
const recommendation = ref<RecommendationList | null>(null); const products = ref<Record<string, any>[]>([]);
const categories = ref<{ categoryId: string; categoryName: string }[]>([]);
const busy = ref(false); const recommendationError = ref(''); const pageRevision = ref(0);
async function loadCategories() {
  try {
    const rows = await javaGet<{ categoryId: string; categoryName: string }[]>('/product/loadCategory');
    categories.value = uniqueCategories(Array.isArray(rows) ? rows : []).slice(0, 8);
  } catch { categories.value = []; }
}
async function load() {
  const requestId = ++pageRevision.value; const requestedOwner = owner.value;
  products.value = []; recommendation.value = null; recommendationError.value = '';
  if (!requestedOwner) { busy.value = false; await loadAds(); return; }
  busy.value = true;
  await recordLanding();
  if (requestId !== pageRevision.value || requestedOwner !== owner.value) return;
  const [recommended] = await Promise.all([
    aiGet<RecommendationList>('/recommendations?limit=4', AbortSignal.timeout(30000)).then(
      (value) => ({ status: 'fulfilled' as const, value }),
      (reason) => ({ status: 'rejected' as const, reason })
    ),
    loadAds(),
  ]);
  if (requestId !== pageRevision.value || requestedOwner !== owner.value) return;
  if (recommended.status === 'fulfilled') {
    const value = recommended.value;
    const items = Array.isArray(value.items) ? value.items.map(item => ({ ...item, recommendation_id: value.recommendation_id })) : null;
    if (items && items.every(item => recommendationTouch(item))) { recommendation.value = value; products.value = items; }
    else recommendationError.value = '推荐列表暂不可用，请稍后刷新。';
  } else recommendationError.value = errorText(recommended.reason);
  busy.value = false;
}
async function select(item: Record<string, any>) {
  await router.push({ path: '/catalog', query: { product: String(item.productId), sku: String(item.propertyValueIds || '') } });
}
watch(owner, (value) => { void load(); if (value) void loadCategories(); }, { immediate: true });
</script>
<style scoped>
.storefront-hero { display: flex; justify-content: space-between; gap: 36px; padding: 42px 44px; margin-bottom: 32px; background: linear-gradient(135deg, #FF5000 0%, #FF8800 58%, #FFD200 100%); border: 0; border-radius: 28px; color: #fffdf8; box-shadow: 0 18px 40px rgba(255, 80, 0, .18); }
.storefront-hero h1 { max-width: 520px; margin: 14px 0 12px; font-size: clamp(32px, 4vw, 48px); letter-spacing: -.04em; color: #fffdf8; }
.storefront-hero p { margin-bottom: 26px; max-width: 460px; color: #e4ddd0; }
.hero-note { min-width: 190px; align-self: center; padding: 8px 0 8px 28px; border-left: 1px solid rgba(255,253,248,.22); }
.hero-note span { font-size: 12px; color: #e8c9a2; letter-spacing: .12em; }.hero-note p { font-size: 22px; margin: 12px 0; color: #fffdf8; }.hero-note a { font-size: 13px; color: #fffdf8; }
.storefront-link { display: inline-block; border: 1px solid rgba(255,253,248,.28); border-radius: 999px; padding: 11px 18px; background: transparent; color: #fffdf8; font: inherit; cursor: pointer; }.storefront-link.primary { background: #fffdf8; color: #FF5000; border-color: #fffdf8; }
.storefront-categories { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }
.storefront-categories a { padding: 8px 16px; border: 1px solid #e4d9c8; border-radius: 999px; background: #fffdf9; font-size: 13px; color: #4d473e; }
.storefront-categories a:hover, .storefront-categories a.router-link-active { border-color: #FF5000; color: #FF5000; background: #FFF1E8; }
.storefront-section { margin: 28px 0 36px; }.storefront-section .page-heading { margin-bottom: 18px; }.storefront-section h2 { font-size: 26px; }.storefront-section .muted { margin-bottom: 0; }
.storefront-section :deep(.agent-products) { max-height: none; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }.storefront-section :deep(.reason) { white-space: normal; }
.ad-label { font-size: 11px; border: 1px solid #d8c4a4; border-radius: 999px; padding: 2px 8px; color: #9a5b2e; vertical-align: middle; font-weight: 500; }.promotion-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.storefront-help { display: flex; align-items: center; justify-content: space-between; gap: 18px; background: #fffdf9; }.storefront-help h2 { font-size: 22px; }.storefront-help a { flex-shrink: 0; border-color: #FF5000; color: #FF5000; }
@media(max-width: 1050px) { .storefront-section :deep(.agent-products) { grid-template-columns: repeat(2, minmax(0, 1fr)); }.hero-note { display: none; } }
@media(max-width: 640px) { .storefront-hero { padding: 28px 22px; }.storefront-help { display: block; }.promotion-grid { grid-template-columns: 1fr; }.storefront-section .page-heading { align-items: center; }.storefront-section .page-heading button { flex-shrink: 0; font-size: 12px; } }
</style>
