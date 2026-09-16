<template>
  <section class="page browse">
    <header class="page-heading">
      <div><p class="eyebrow">全部商品</p><h1>慢慢逛，按自己的节奏。</h1><p class="muted">这里是当前店铺可售商品，不含推广位。分类、价格和排序都来自商品库本身。</p></div>
      <button type="button" :disabled="busy || !session" @click="load">刷新列表</button>
    </header>

    <form class="browse-search" @submit.prevent="submitFilters">
      <label>搜索商品名<input v-model="keywordInput" maxlength="50" placeholder="例如 键盘、杯子" /></label>
      <label>最低价（元）<input v-model="priceFromInput" type="number" min="0" step="0.01" placeholder="不限" /></label>
      <label>最高价（元）<input v-model="priceToInput" type="number" min="0" step="0.01" placeholder="不限" /></label>
      <label>排序<select v-model="sortInput">
        <option value="">综合</option><option value="PRICE:ASC">价格从低到高</option>
        <option value="PRICE:DESC">价格从高到低</option><option value="SALE:DESC">销量优先</option>
      </select></label>
      <button type="submit" class="primary" :disabled="busy || !session">{{ busy ? '正在查询…' : '查询' }}</button>
    </form>

    <nav v-if="categories.length" class="category-nav" aria-label="商品分类">
      <button type="button" :class="{ selected: !categoryId }" @click="pick('')">全部</button>
      <button v-for="item in categories" :key="item.categoryId" type="button"
              :class="{ selected: categoryId === item.categoryId }" @click="pick(item.categoryId)">{{ item.categoryName }}</button>
    </nav>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="!error && !busy" class="muted" role="status">{{ summary }}</p>

    <AgentProductList :list="products" @select="select" />

    <nav v-if="pageTotal > 1" class="browse-pager" aria-label="分页">
      <button type="button" :disabled="busy || pageNo <= 1" @click="turn(pageNo - 1)">上一页</button>
      <span class="muted">第 {{ pageNo }} / {{ pageTotal }} 页</span>
      <button type="button" :disabled="busy || pageNo >= pageTotal" @click="turn(pageNo + 1)">下一页</button>
    </nav>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AgentProductList from '@/components/agent/AgentProductList.vue';
import { errorText, javaGet, javaPost, ownerKey, session } from '@/api/client';
import { recordLanding } from '@/api/traffic';
import { uniqueCategories } from '@/utils/productDisplay';
import { excludeProductIds, loadProductScope } from '@/utils/productScope';
import {
  ProductQueryError,
  normalizePrice,
  normalizeSort
} from '@/utils/productQuery';

interface Category { categoryId: string; categoryName: string }

const route = useRoute();
const router = useRouter();
const owner = computed(() => session.value ? ownerKey(session.value.actor) : '');
const categories = ref<Category[]>([]);
const products = ref<Record<string, any>[]>([]);
const totalCount = ref(0);
const pageTotal = ref(1);
const busy = ref(false);
const error = ref('');
const keywordInput = ref('');
const priceFromInput = ref('');
const priceToInput = ref('');
const sortInput = ref('');
let listRequest = 0;

const text = (value: unknown) => (typeof value === 'string' ? value : '');
const keyword = computed(() => text(route.query.keyword).slice(0, 50));
const categoryId = computed(() => text(route.query.category));
// Every filter lives in the URL so one watcher drives every reload and a filtered list stays
// linkable. Keeping price or sort in local state only would silently do nothing when the rest
// of the query is unchanged.
const priceFrom = computed(() => text(route.query.priceFrom));
const priceTo = computed(() => text(route.query.priceTo));
const sort = computed(() => text(route.query.sort));
const pageNo = computed(() => {
  const raw = Number(route.query.page);
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
});
const summary = computed(() => {
  if (!products.value.length) return keyword.value ? `没有匹配“${keyword.value}”的在售商品。` : '当前筛选没有在售商品。';
  return `共 ${totalCount.value} 件在售商品${keyword.value ? `匹配“${keyword.value}”` : ''}。`;
});

async function loadCategories() {
  try {
    const rows = await javaGet<Category[]>('/product/loadCategory');
    categories.value = uniqueCategories(Array.isArray(rows) ? rows : []);
  } catch { categories.value = []; }
}

async function load() {
  if (!session.value) return;
  const requestId = ++listRequest;
  const requestedOwner = owner.value;
  busy.value = true; error.value = ''; products.value = [];
  try {
    const values: Record<string, string | number> = { pageNo: pageNo.value };
    if (keyword.value) values.keyword = keyword.value;
    if (categoryId.value) values.categoryId = categoryId.value;
    const from = normalizePrice(priceFrom.value);
    const to = normalizePrice(priceTo.value);
    if (from !== undefined) values.priceFrom = from;
    if (to !== undefined) values.priceTo = to;
    if (from !== undefined && to !== undefined && Number(from) > Number(to)) {
      throw new ProductQueryError('最低价不能高于最高价。');
    }
    const sortQuery = normalizeSort(sort.value);
    if (sortQuery.sortKey) {
      values.sortKey = sortQuery.sortKey;
      if (sortQuery.sortDirection) values.sortDirection = sortQuery.sortDirection;
    }
    const excluded = excludeProductIds(await loadProductScope(requestedOwner));
    if (excluded) values.excludeProductIds = excluded;
    await recordLanding();
    if (requestId !== listRequest || requestedOwner !== owner.value) return;
    const page = await javaPost<{ list?: Record<string, any>[]; totalCount?: number; pageTotal?: number }>('/product/loadProduct', values);
    if (requestId !== listRequest || requestedOwner !== owner.value) return;
    // Catalogue rows carry no recommendation receipt, so AgentProductList reports no touch for
    // them. Browsing the shelf is not a recommendation impression and must not be counted as one.
    products.value = Array.isArray(page?.list) ? page.list : [];
    totalCount.value = Number(page?.totalCount) || 0;
    pageTotal.value = Math.max(1, Number(page?.pageTotal) || 1);
  } catch (reason) {
    if (requestId === listRequest && requestedOwner === owner.value) error.value = errorText(reason);
  } finally {
    if (requestId === listRequest) busy.value = false;
  }
}

async function navigate(changes: Record<string, string>) {
  // Any filter change resets to page one unless the change is the page itself.
  const query = { keyword: keyword.value, category: categoryId.value, priceFrom: priceFrom.value,
    priceTo: priceTo.value, sort: sort.value, page: '', ...changes };
  await router.replace({ path: '/browse', query: Object.fromEntries(Object.entries(query).filter(([, value]) => value)) });
}
// A number input can hand back a number, so every field is stringified before trimming.
const submitFilters = () => navigate({ keyword: String(keywordInput.value).trim().slice(0, 50),
  priceFrom: String(priceFromInput.value).trim(), priceTo: String(priceToInput.value).trim(),
  sort: String(sortInput.value) });
const pick = (id: string) => navigate({ category: id });
const turn = (page: number) => navigate({ page: String(page) });
const select = (item: Record<string, any>) =>
  router.push({ path: '/catalog', query: { product: String(item.productId) } });

watch(owner, (value) => { if (value) void loadCategories(); }, { immediate: true });
watch(() => [owner.value, keyword.value, categoryId.value, priceFrom.value, priceTo.value, sort.value, pageNo.value], () => {
  keywordInput.value = keyword.value;
  priceFromInput.value = priceFrom.value;
  priceToInput.value = priceTo.value;
  sortInput.value = sort.value;
  if (owner.value) void load(); else { products.value = []; busy.value = false; }
}, { immediate: true });
</script>

<style scoped>
.browse-search { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 14px; margin-bottom: 18px; padding: 18px; background: #fffdf9; border: 1px solid #e4d9c8; border-radius: 20px; }
.browse-search label { flex: 1; min-width: 130px; margin: 0; }
.browse-search button { min-height: 44px; }
.category-nav { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
.category-nav button { padding: 8px 16px; border: 1px solid #e4d9c8; border-radius: 999px; background: #fffdf9; font-size: 13px; cursor: pointer; }
.category-nav button.selected { background: $color-primary; border-color: $color-primary; color: #fff; }
.browse :deep(.agent-products) { max-height: none; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.browse-pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 24px; }
@media(max-width: 1050px) { .browse :deep(.agent-products) { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
