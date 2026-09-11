import { computed, ref } from 'vue';
import { aiGet, ownerKey, session } from '@/api/client';
import type { Promotion } from '@/api/traffic';

export function usePromotions(limit = 2) {
  const ads = ref<Promotion[]>([]);
  const revision = ref(0);
  const loading = ref(false);
  const owner = computed(() => (session.value ? ownerKey(session.value.actor) : ''));

  async function load() {
    const requestId = ++revision.value;
    const requestedOwner = owner.value;
    if (!requestedOwner) {
      ads.value = [];
      loading.value = false;
      return;
    }
    loading.value = true;
    try {
      const result = await aiGet<{ items: Promotion[] }>(
        `/ads/recommendations?limit=${limit}`,
        AbortSignal.timeout(30000)
      );
      if (requestId !== revision.value || requestedOwner !== owner.value) return;
      ads.value = Array.isArray(result.items) ? result.items : [];
    } catch {
      if (requestId === revision.value && requestedOwner === owner.value) ads.value = [];
    } finally {
      if (requestId === revision.value) loading.value = false;
    }
  }

  return { ads, owner, revision, loading, load };
}
