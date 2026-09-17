import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { productApi } from '@/api/modules';
import { usePageListCache } from '@/composables/usePageListCache';
import { usePagedList } from '@/composables/usePagedList';
import { usePageRefresh } from '@/composables/pullRefresh';
import { useSearchStore } from '@/stores/search';
import { filterStorefrontProducts } from '@/utils/product';
import { ProductQueryError, normalizePriceRange } from '@/utils/productQuery';
import { sortModeToQuery, sortQueryToMode, type SortMode } from '@/utils/productSort';
import { toast } from '@/utils/toast';

/**
 * 搜索结果页的共用逻辑：移动端与 PC 两份原来各自复制了一遍查询状态、缓存键、
 * 加载/重置、店铺同步与路由监听（PC 那份还漏了价格校验），现在只保留模板差异。
 */
export function useSearchPage(options: { scope: 'mobile' | 'pc' }) {
  const route = useRoute();
  const router = useRouter();
  const searchStore = useSearchStore();

  const sentinelRef = ref<HTMLElement | null>(null);
  const activeKeywords = ref('');
  const loadError = ref('');

  const query = reactive({
    keyWords: searchStore.payload.keyWords,
    priceFrom: searchStore.payload.priceFrom,
    priceTo: searchStore.payload.priceTo,
    sortKey: searchStore.payload.sortKey,
    sortDirection: searchStore.payload.sortDirection
  });

  const sortMode = computed<SortMode>({
    get: () => sortQueryToMode(query.sortKey, query.sortDirection),
    set: (mode) => Object.assign(query, sortModeToQuery(mode))
  });

  const resolveKeywords = () => {
    const fromQuery = typeof route.query.q === 'string' ? route.query.q.trim() : '';
    if (fromQuery) return fromQuery;
    return searchStore.payload.keyWords.trim();
  };

  const paged = usePagedList<any>({
    sentinel: sentinelRef,
    canLoad: () => !!query.keyWords.trim(),
    transform: (rows) => filterStorefrontProducts(rows),
    fetchPage: async (next) => {
      const keyWords = query.keyWords.trim();
      activeKeywords.value = keyWords;
      loadError.value = '';
      // 手改链接/输入框里的价格不能原样转给 Java
      const range = normalizePriceRange(query.priceFrom, query.priceTo);
      return productApi.searchProducts({
        keyWords,
        pageNo: next,
        categoryId: searchStore.payload.categoryId || undefined,
        priceFrom: range.priceFrom,
        priceTo: range.priceTo,
        sortKey: query.sortKey || undefined,
        sortDirection: query.sortDirection || undefined
      });
    },
    onError: (reason: any) => {
      loadError.value = reason instanceof ProductQueryError
        ? reason.message
        : reason?.info || reason?.message || '搜索失败，请稍后重试';
    }
  });
  const { pageNo, pageTotal, total, list, loading, loadingMore, finished, loadMore, setupObserver } = paged;

  const cacheKey = () =>
    [
      options.scope === 'pc' ? '/search-result|pc' : '/search-result',
      query.keyWords.trim(),
      query.priceFrom,
      query.priceTo,
      query.sortKey,
      query.sortDirection,
      searchStore.payload.categoryId
    ].join('|');

  const pageCache = usePageListCache({
    cacheKey,
    getState: () => ({
      query: { ...query },
      list: list.value,
      pageNo: pageNo.value,
      pageTotal: pageTotal.value,
      total: total.value,
      finished: finished.value,
      activeKeywords: activeKeywords.value
    }),
    setState: (state) => {
      const restored = state.query as typeof query;
      if (restored) Object.assign(query, restored);
      paged.restore(state);
      activeKeywords.value = String(state.activeKeywords ?? '');
    },
    afterRestore: setupObserver
  });

  const syncStore = (keyWords: string) => {
    searchStore.setSearch({
      keyWords,
      categoryId: searchStore.payload.categoryId,
      priceFrom: query.priceFrom,
      priceTo: query.priceTo,
      sortKey: query.sortKey,
      sortDirection: query.sortKey === 'PRICE' ? query.sortDirection : ''
    });
  };

  const resetAndLoad = () => {
    paged.reset();
    window.scrollTo(0, 0);
    void loadMore();
  };

  const onSortChange = () => {
    if (!query.keyWords.trim()) return;
    pageCache.clear();
    syncStore(query.keyWords.trim());
    resetAndLoad();
  };

  const onSearch = () => {
    pageCache.clear();
    const keyWords = query.keyWords.trim();
    if (!keyWords) {
      toast.warning('请输入搜索关键词');
      return;
    }
    if (query.sortKey === 'PRICE' && !query.sortDirection) query.sortDirection = 'DESC';
    syncStore(keyWords);
    if (route.query.q !== keyWords) {
      router.replace({ path: '/search-result', query: { q: keyWords } });
    }
    resetAndLoad();
  };

  const applySearch = (keyWords: string) => {
    searchStore.setSearch({ ...searchStore.payload, keyWords });
    query.keyWords = keyWords;
    activeKeywords.value = keyWords;
    resetAndLoad();
  };

  const goDetail = (product: any) => router.push(`/product/${product.productId}`);

  onMounted(async () => {
    const keyWords = resolveKeywords();
    if (!keyWords) {
      router.replace('/search');
      return;
    }
    Object.assign(query, searchStore.payload);
    query.keyWords = keyWords;
    const restored = await pageCache.tryRestore();
    if (!restored) applySearch(keyWords);
    else activeKeywords.value = query.keyWords.trim();
    setupObserver();
  });

  watch(
    () => route.query.q,
    (value) => {
      if (typeof value !== 'string') return;
      const keyWords = value.trim();
      if (!keyWords || keyWords === query.keyWords.trim()) return;
      applySearch(keyWords);
    }
  );

  usePageRefresh(() => {
    pageCache.clear();
    resetAndLoad();
  });

  onUnmounted(() => paged.disconnect());

  return {
    query, sortMode, activeKeywords, loadError,
    pageNo, pageTotal, total, list, loading, loadingMore, finished,
    sentinelRef, onSearch, onSortChange, goDetail, resetAndLoad,
    // 哨兵滚动由 composable 内部驱动；暴露出来供"重试/测试"按需手动触发下一页
    loadMore
  };
}
