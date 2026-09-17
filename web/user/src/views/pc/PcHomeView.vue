<template>
  <div class="sl-home-page ignore">
    <PcSmartlectHomeScreen :categories="rootCategories" :hot-products="hotProducts" :promotions="ads" />

    <section class="sl-home-feed">
      <h2 class="sl-feed-title">猜你喜欢</h2>
      <el-skeleton :loading="loading" animated :count="1">
        <template #template>
          <div class="sl-feed-grid">
            <el-skeleton-item v-for="n in 10" :key="n" variant="image" style="aspect-ratio: 1" />
          </div>
        </template>
        <div v-if="displayProducts.length" class="sl-feed-grid">
          <article
            v-for="item in displayProducts"
            :key="`${item.product.productId}-${item.displayIndex}`"
            class="sl-feed-tile"
            @click="goDetail(item.product)"
          >
            <div class="sl-feed-cover">
              <ProductImage :product="item.product" fit="contain" width="100%" height="100%" />
            </div>
            <p class="sl-feed-name">{{ item.product.productName }}</p>
            <p class="sl-feed-price"><span class="sym">¥</span>{{ formatPrice(item.product) }}</p>
          </article>
        </div>
        <el-empty v-else description="暂无商品，稍后再来看看" />
      </el-skeleton>
      <div ref="feedSentinel" class="sl-feed-sentinel">
        <span v-if="feedLoading" class="feed-tip">加载中…</span>
        <span v-else-if="feedFinished && displayProducts.length >= MAX_PRODUCTS" class="feed-tip">已展示全部推荐商品</span>
        <span v-else-if="feedFinished && displayProducts.length" class="feed-tip">没有更多了</span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import ProductImage from '@/components/common/ProductImage.vue';
import PcSmartlectHomeScreen from '@/components/home/PcSmartlectHomeScreen.vue';
import { productApi } from '@/api/modules';
import { usePageRefresh } from '@/composables/pullRefresh';
import { usePromotions } from '@/composables/usePromotions';
import { storefrontCategoryTree } from '@/utils/category';
import { filterStorefrontProducts, splitStorefrontPage } from '@/utils/product';

const router = useRouter();
const { ads, owner, load: loadAds } = usePromotions(2);
const categories = ref<any[]>([]);
const hotProductsList = ref<any[]>([]);
const products = ref<any[]>([]);
const loading = ref(true);

const feedSentinel = ref<HTMLElement | null>(null);
const feedPageNo = ref(0);
const feedPageTotal = ref(1);
const feedLoading = ref(false);
const feedFinished = ref(false);
const MAX_PRODUCTS = 120;
let feedObserver: IntersectionObserver | null = null;

const displayProducts = computed(() => {
  return products.value
    .slice(0, MAX_PRODUCTS)
    .map((product, displayIndex) => ({ product, displayIndex }));
});

const rootCategories = computed(() => storefrontCategoryTree(categories.value));
const hotProducts = computed(() => hotProductsList.value.slice(0, 10));

const formatPrice = (p: Record<string, any>) => {
  const val = p.minPrice ?? p.price ?? p.salePrice;
  return val != null ? Number(val).toFixed(2) : '--';
};

let feedCancelled = false;

const loadFeed = async (reset = false) => {
  if (feedCancelled || feedLoading.value) return;

  if (reset) {
    feedPageNo.value = 0;
    feedPageTotal.value = 1;
    feedFinished.value = false;
    products.value = [];
  }

  if (feedFinished.value) return;

  feedLoading.value = true;
  try {
    const next = feedPageNo.value + 1;
    const page = await productApi.loadProduct({ pageNo: next });
    const { visible, fetched } = splitStorefrontPage(page?.list);

    if (feedCancelled) return;
    if (visible.length > 0) {
      const existingIds = new Set(products.value.map(p => p.productId));
      const filtered = visible.filter(p => !existingIds.has(p.productId));
      products.value = products.value.concat(filtered);
    }

    feedPageNo.value = Number(page?.pageNo) || next;
    feedPageTotal.value = Number(page?.pageTotal) || feedPageNo.value;

    const hasMoreData = fetched > 0 && feedPageNo.value < feedPageTotal.value;
    const reachedMax = products.value.length >= MAX_PRODUCTS;

    if (!hasMoreData || reachedMax) {
      feedFinished.value = true;
    }
  } catch (error) {
    console.error('PcHomeView: loadFeed error', error);
  } finally {
    feedLoading.value = false;
  }
};

const load = async () => {
  loading.value = true;
  try {
    const [cats, commend] = await Promise.all([
      productApi.loadCategory(),
      productApi.loadCommendProduct()
    ]);
    categories.value = Array.isArray(cats) ? cats : [];
    hotProductsList.value = filterStorefrontProducts(Array.isArray(commend) ? commend : commend?.list);
    await loadFeed(true);
  } finally {
    loading.value = false;
  }
};

const goDetail = (p: any) => {
  if (p?.productId) router.push(`/product/${p.productId}`);
};

const setupInfiniteScroll = async () => {
  await nextTick();

  if (!feedSentinel.value) {
    console.warn('PcHomeView: feedSentinel not found');
    return;
  }

  feedObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && !feedLoading.value && !feedFinished.value) {
          loadFeed();
        }
      }
    },
    {
      root: null,
      rootMargin: '300px 0px',
      threshold: 0.01
    }
  );

  feedObserver.observe(feedSentinel.value);
};

onMounted(async () => {
  await load();
  setupInfiniteScroll();
});

onUnmounted(() => {
  feedCancelled = true;
  if (feedObserver) {
    feedObserver.disconnect();
    feedObserver = null;
  }
});

watch(owner, (value) => { void (value ? loadAds() : Promise.resolve(ads.value = [])); }, { immediate: true });

usePageRefresh(async () => {
  await Promise.all([load(), loadAds()]);
});
</script>
