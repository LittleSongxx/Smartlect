import { describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import { usePagedList } from '../src/composables/usePagedList';

const page = (list: number[], pageTotal: number, totalCount: number, pageNo: number) =>
  ({ list, pageTotal, totalCount, pageNo });

describe('列表页分页/无限滚动机制', () => {
  it('首页加载后翻页是追加而不是替换', async () => {
    const fetchPage = vi.fn(async (no: number) => no === 1
      ? page([1, 2], 2, 4, 1)
      : page([3, 4], 2, 4, 2));
    const paged = usePagedList<number>({ fetchPage });

    await paged.loadMore();
    expect(paged.list.value).toEqual([1, 2]);
    expect(paged.total.value).toBe(4);
    expect(paged.finished.value).toBe(false);

    await paged.loadMore();
    expect(paged.list.value).toEqual([1, 2, 3, 4]);
    expect(paged.finished.value).toBe(true);
    expect(fetchPage).toHaveBeenCalledTimes(2);

    await paged.loadMore();  // 已到底不再发请求
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });

  it('reset 之后从第一页重新拉', async () => {
    const fetchPage = vi.fn(async () => page([1], 1, 1, 1));
    const paged = usePagedList<number>({ fetchPage });
    await paged.loadMore();
    paged.reset();
    expect(paged.list.value).toEqual([]);
    expect(paged.pageNo.value).toBe(0);
    await paged.loadMore();
    expect(fetchPage).toHaveBeenLastCalledWith(1);
  });

  it('transform 作用于每一页，canLoad 为假时不发请求', async () => {
    const fetchPage = vi.fn(async () => page([1, 2, 3], 1, 3, 1));
    let ready = false;
    const paged = usePagedList<number>({
      fetchPage,
      canLoad: () => ready,
      transform: (rows) => rows.filter((n) => n > 1)
    });
    await paged.loadMore();
    expect(fetchPage).not.toHaveBeenCalled();
    ready = true;
    await paged.loadMore();
    expect(paged.list.value).toEqual([2, 3]);
  });

  it('失败时结束加载并把错误交给页面处理', async () => {
    const error = new Error('boom');
    const onError = vi.fn();
    const paged = usePagedList<number>({ fetchPage: async () => { throw error; }, onError });
    await paged.loadMore();
    expect(onError).toHaveBeenCalledWith(error);
    expect(paged.finished.value).toBe(true);
    expect(paged.loadingMore.value).toBe(false);
  });

  it('缓存快照与恢复保持列表与页码', async () => {
    const paged = usePagedList<number>({ fetchPage: async () => page([1, 2], 3, 6, 1) });
    await paged.loadMore();
    const state = {
      list: paged.list.value, pageNo: paged.pageNo.value,
      pageTotal: paged.pageTotal.value, total: paged.total.value, finished: paged.finished.value
    };
    const restored = usePagedList<number>({ fetchPage: async () => page([], 1, 0, 0) });
    restored.restore(state);
    expect(restored.list.value).toEqual([1, 2]);
    expect(restored.pageNo.value).toBe(1);
    expect(restored.pageTotal.value).toBe(3);
    expect(restored.total.value).toBe(6);
    expect(restored.finished.value).toBe(false);
  });

  it('没有哨兵元素时不抛错（jsdom 无 IntersectionObserver 也要安全）', () => {
    const paged = usePagedList<number>({ fetchPage: async () => page([], 1, 0, 0), sentinel: ref(null) });
    expect(() => paged.setupObserver()).not.toThrow();
  });
});
