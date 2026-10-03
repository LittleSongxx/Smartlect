import { computed, ref } from 'vue';
import { ownerKey, session } from '@/api/client';
import { productApi } from '@/api/modules';

/**
 * 首页「为你推荐」位：2026-10 收敛重构后改走 Java 目录的确定性精选
 * （管理端配置的 commend 商品，接口 /product/loadCommendProduct），
 * 不再经过 assistant 的推荐/归因线。
 */
export function useHomeRecommendations(limit = 4) {
  const items = ref<Record<string, any>[]>([]);
  const recommendationId = ref('');
  const rankingMode = ref('catalog:commend');
  const revision = ref(0);
  const loading = ref(false);
  const owner = computed(() => (session.value ? ownerKey(session.value.actor) : ''));

  async function load() {
    const requestId = ++revision.value;
    loading.value = true;
    try {
      const list = await productApi.loadCommendProduct();
      if (requestId !== revision.value) return;
      const rows = Array.isArray(list) ? list : [];
      items.value = rows.slice(0, limit).map((row: Record<string, any>) => ({ ...row, kind: 'recommend' }));
      recommendationId.value = '';
    } catch {
      if (requestId === revision.value) items.value = [];
    } finally {
      if (requestId === revision.value) loading.value = false;
    }
  }

  function touchFor(_item: Record<string, any>) {
    return null;
  }

  async function rememberClick(_item: Record<string, any>) {
    // 确定性精选位没有点击归因上报。
  }

  return { items, recommendationId, rankingMode, owner, revision, loading, load, rememberClick };
}
