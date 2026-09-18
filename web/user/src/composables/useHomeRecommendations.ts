import { computed, ref } from 'vue';
import { aiGet, ownerKey, session } from '@/api/client';
import {
  recordLanding,
  recommendationTouch,
  reportClick,
  reportExposure,
  type RecommendationList,
  type RecommendationTouch,
} from '@/api/traffic';

export function useHomeRecommendations(limit = 4) {
  const items = ref<Record<string, any>[]>([]);
  const recommendationId = ref('');
  const rankingMode = ref('');
  const revision = ref(0);
  const loading = ref(false);
  const owner = computed(() => (session.value ? ownerKey(session.value.actor) : ''));

  async function load() {
    const requestId = ++revision.value;
    const requestedOwner = owner.value;
    if (!requestedOwner) {
      items.value = [];
      recommendationId.value = '';
      rankingMode.value = '';
      loading.value = false;
      return;
    }
    loading.value = true;
    try {
      await recordLanding();
      if (requestId !== revision.value || requestedOwner !== owner.value) return;
      const result = await aiGet<RecommendationList>(
        `/recommendations?limit=${limit}`,
        AbortSignal.timeout(30000)
      );
      if (requestId !== revision.value || requestedOwner !== owner.value) return;
      const rows = Array.isArray(result.items)
        ? result.items.map((item) => ({ ...item, recommendation_id: result.recommendation_id }))
        : [];
      const valid = rows.filter((row) => recommendationTouch(row));
      items.value = valid;
      recommendationId.value = typeof result.recommendation_id === 'string' ? result.recommendation_id : '';
      rankingMode.value = typeof result.ranking_mode === 'string' ? result.ranking_mode : '';
      const positions = valid
        .map((row) => recommendationTouch(row)?.position)
        .filter((position): position is number => typeof position === 'number');
      if (recommendationId.value && positions.length) {
        void reportExposure(recommendationId.value, positions);
      }
    } catch {
      if (requestId === revision.value && requestedOwner === owner.value) {
        items.value = [];
        recommendationId.value = '';
        rankingMode.value = '';
      }
    } finally {
      if (requestId === revision.value) loading.value = false;
    }
  }

  function touchFor(item: Record<string, any>): RecommendationTouch | null {
    return recommendationTouch(item);
  }

  async function rememberClick(item: Record<string, any>) {
    const touch = touchFor(item);
    if (touch) await reportClick(touch);
  }

  return { items, recommendationId, rankingMode, owner, revision, loading, load, rememberClick };
}
