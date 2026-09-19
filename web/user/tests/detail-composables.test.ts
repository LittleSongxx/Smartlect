import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
import { productApi, userMemberApi } from '../src/api/modules';
import { useSimilarProducts } from '../src/composables/useSimilarProducts';
import { useCommentLevels } from '../src/composables/useCommentLevels';

// 这两个 composable 原来在两个商品详情页里各写一份且没有测试：这里锁住"推荐位铺满 + 分批放出
// 不超过上限 + 触底才加载"与"等级缓存去重 + 档位类名"的语义。
const Host = (setup: () => Record<string, unknown>) => defineComponent({ setup, template: '<div />' });

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('useSimilarProducts', () => {
  it('推荐位不足时铺满到上限，分批放出且不超上限', async () => {
    vi.spyOn(productApi, 'loadCommendProduct').mockResolvedValue([
      { productId: 'p1', productName: 'A', status: 1 },
      { productId: 'p2', productName: 'B', status: 1 }
    ] as any);
    let api: any;
    const wrapper = mount(Host(() => { api = useSimilarProducts({ pageSize: 2, max: 6, label: 'test' }); return {}; }));
    await flushPromises();
    expect(api.allSimilarProducts.value).toHaveLength(6);   // 两份商品铺满到上限
    expect(api.similarProducts.value.map((p: any) => p.productId)).toEqual(['p1', 'p2']);

    api.loadMore();
    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(api.similarProducts.value).toHaveLength(4);
    expect(api.finished.value).toBe(false);

    api.loadMore();
    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(api.similarProducts.value).toHaveLength(6);
    expect(api.finished.value).toBe(true);

    api.loadMore();  // 已到底不再变化
    expect(api.similarProducts.value).toHaveLength(6);
    wrapper.unmount();
  });

  it('没有推荐位时直接结束，不留下假加载状态', async () => {
    vi.spyOn(productApi, 'loadCommendProduct').mockResolvedValue([] as any);
    let api: any;
    const wrapper = mount(Host(() => { api = useSimilarProducts({ pageSize: 2, max: 6, label: 'test' }); return {}; }));
    await flushPromises();
    expect(api.finished.value).toBe(true);
    expect(api.loadingMore.value).toBe(false);
    wrapper.unmount();
  });
});

describe('useCommentLevels', () => {
  it('同一位用户只查一次，档位类名按基线档传入', async () => {
    const getLevelBadge = vi.spyOn(userMemberApi, 'getLevelBadge').mockResolvedValue({ levelCode: 3, levelName: '金卡会员' } as any);
    let api: any;
    const wrapper = mount(Host(() => { api = useCommentLevels({ baseClass: 'level-normal' }); return {}; }));

    api.fetchLevels([{ userId: 'u1' }, { userId: 'u1' }, { userId: '' }]);
    await flushPromises();
    expect(getLevelBadge).toHaveBeenCalledTimes(1);
    expect(api.getLevel('u1')).toMatchObject({ levelCode: 3 });

    api.fetchLevels([{ userId: 'u1' }]);   // 已缓存不再请求
    expect(getLevelBadge).toHaveBeenCalledTimes(1);

    expect(api.tagClass(3)).toBe('level-gold');
    expect(api.tagClass(2)).toBe('level-silver');
    expect(api.tagClass(1)).toBe('level-normal');
    wrapper.unmount();
  });

  it('等级取不到时不抛错也不显示', async () => {
    vi.spyOn(userMemberApi, 'getLevelBadge').mockRejectedValue(new Error('boom'));
    let api: any;
    const wrapper = mount(Host(() => { api = useCommentLevels(); return {}; }));
    api.fetchLevel('u9');
    await flushPromises();
    expect(api.getLevel('u9')).toBeNull();
    expect(api.tagClass(1)).toBe('level-default');   // 默认基线档
    wrapper.unmount();
  });
});
