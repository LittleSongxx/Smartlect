import { onMounted, onUnmounted, ref } from 'vue';
import { productApi } from '@/api/modules';
import { filterStorefrontProducts } from '@/utils/product';

/**
 * 商品详情页的"猜你喜欢"：移动端与 PC 两份原来各有一份滚动触底 + 分批放出的实现
 * （连 requestAnimationFrame 节流和 300ms 假加载都一样），只有页尺寸/上限不同。
 */
export function useSimilarProducts(options: { pageSize: number; max: number; label: string }) {
  const similarProducts = ref<any[]>([]);
  const loadingMore = ref(false);
  const finished = ref(false);
  const allSimilarProducts = ref<any[]>([]);
  const displayCount = ref(options.pageSize);
  let ticking = false;

  const loadMore = () => {
    if (finished.value || loadingMore.value) return;
    if (displayCount.value >= allSimilarProducts.value.length) {
      finished.value = true;
      return;
    }
    loadingMore.value = true;
    setTimeout(() => {
      displayCount.value = Math.min(
        displayCount.value + options.pageSize,
        options.max,
        allSimilarProducts.value.length
      );
      similarProducts.value = allSimilarProducts.value.slice(0, displayCount.value);
      if (displayCount.value >= allSimilarProducts.value.length) finished.value = true;
      loadingMore.value = false;
    }, 300);
  };

  const onScroll = () => {
    if (ticking || finished.value || loadingMore.value) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const scrolled = window.scrollY || document.documentElement.scrollTop;
      const height = document.documentElement.scrollHeight;
      if (height - scrolled - window.innerHeight < 200) loadMore();
    });
  };

  const loadSimilarProducts = async () => {
    loadingMore.value = true;
    try {
      const data = await productApi.loadCommendProduct();
      const list = filterStorefrontProducts(Array.isArray(data) ? data : data?.list || []);
      if (!list.length) {
        finished.value = true;
        return;
      }
      // 推荐位不足时重复铺满，保证"猜你喜欢"区域有内容
      let filled = [...list];
      while (filled.length < options.max) filled = filled.concat(list);
      allSimilarProducts.value = filled.slice(0, options.max);
      similarProducts.value = allSimilarProducts.value.slice(0, displayCount.value);
      if (allSimilarProducts.value.length <= displayCount.value) finished.value = true;
    } catch (error) {
      console.error(`${options.label}: loadSimilarProducts error`, error);
      finished.value = true;
    } finally {
      loadingMore.value = false;
    }
  };

  onMounted(() => {
    void loadSimilarProducts();
    window.addEventListener('scroll', onScroll, { passive: true });
  });
  onUnmounted(() => window.removeEventListener('scroll', onScroll));

  return { similarProducts, loadingMore, finished, allSimilarProducts, displayCount, loadMore, onScroll, loadSimilarProducts };
}
