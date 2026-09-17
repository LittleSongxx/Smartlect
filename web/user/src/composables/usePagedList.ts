import { ref, type Ref } from 'vue';

export type PagedResult<T> = {
  list?: T[] | null;
  pageTotal?: number;
  totalCount?: number;
  pageNo?: number;
} | null | undefined;

export type UsePagedListOptions<T> = {
  /** 取第 pageNo 页（从 1 开始）；返回 null/undefined 视为"无更多数据"。 */
  fetchPage: (pageNo: number) => Promise<PagedResult<T>>;
  /** 结果进入列表前的转换（例如门店范围过滤）。 */
  transform?: (rows: T[]) => T[];
  /** 加载前的守卫（例如关键词为空就不查）。返回 false 直接中止。 */
  canLoad?: () => boolean;
  onError?: (error: unknown) => void;
  /** 滚到底触发加载的哨兵元素。 */
  sentinel?: Ref<HTMLElement | null | undefined>;
  rootMargin?: string;
};

/**
 * 列表页共用的"分页 + 无限滚动"机制：分类页、搜索结果页原来各写一份
 * pageNo/pageTotal/finished/loadingMore + IntersectionObserver + 追加逻辑，
 * 任何一处改语义都会让两个页面的行为分叉。
 */
export function usePagedList<T>(options: UsePagedListOptions<T>) {
  const pageNo = ref(0);
  const pageTotal = ref(1);
  const total = ref(0);
  const list = ref([]) as Ref<T[]>;
  const loading = ref(false);
  const loadingMore = ref(false);
  const finished = ref(false);

  let observer: IntersectionObserver | null = null;

  const disconnect = () => {
    observer?.disconnect();
    observer = null;
  };

  const setupObserver = () => {
    disconnect();
    const element = options.sentinel?.value;
    if (!element || typeof IntersectionObserver === 'undefined') return;
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: options.rootMargin ?? '120px' }
    );
    observer.observe(element);
  };

  const loadMore = async () => {
    if (loadingMore.value || finished.value) return;
    if (options.canLoad && !options.canLoad()) return;
    if (pageNo.value >= pageTotal.value && pageNo.value > 0) {
      finished.value = true;
      return;
    }
    loadingMore.value = true;
    if (!list.value.length) loading.value = true;
    try {
      const next = pageNo.value + 1;
      const result = await options.fetchPage(next);
      const rows = options.transform ? options.transform(result?.list ?? []) : (result?.list ?? []);
      list.value = next <= 1 ? rows : list.value.concat(rows);
      pageNo.value = result?.pageNo ?? next;
      pageTotal.value = result?.pageTotal ?? pageNo.value;
      total.value = result?.totalCount ?? list.value.length;
      finished.value = pageNo.value >= pageTotal.value;
    } catch (error) {
      finished.value = true;
      options.onError?.(error);
    } finally {
      loadingMore.value = false;
      loading.value = false;
    }
  };

  const reset = () => {
    pageNo.value = 0;
    pageTotal.value = 1;
    finished.value = false;
    list.value = [] as unknown as T[];
    total.value = 0;
  };

  const restore = (state: {
    list?: unknown;
    pageNo?: unknown;
    pageTotal?: unknown;
    total?: unknown;
    finished?: unknown;
  }) => {
    list.value = (state.list as T[]) || ([] as unknown as T[]);
    pageNo.value = Number(state.pageNo) || 0;
    pageTotal.value = Number(state.pageTotal) || 1;
    total.value = Number(state.total) || 0;
    finished.value = !!state.finished;
    loading.value = false;
    loadingMore.value = false;
  };

  return {
    pageNo, pageTotal, total, list, loading, loadingMore, finished,
    loadMore, reset, restore, setupObserver, disconnect
  };
}
