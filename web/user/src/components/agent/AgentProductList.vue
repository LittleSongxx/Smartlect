<template>
  <div ref="container" class="agent-products">
    <article v-for="(item, index) in list" :key="`${item.recommendation_id || item.productId}:${item.position || item.propertyValueIds || index}`" class="product-tile">
      <button type="button" class="product-link" @click="select(item)">
        <ProductImage class="tile-cover" :product="item" width="100%" height="176" />
        <div class="tile-body">
        <div class="title-row"><p class="name">{{ item.productName }}</p></div>
        <p class="price">{{ item.price_cents != null ? money(item.price_cents) : priceText(item) }}</p>
        <p v-if="typeof item.specification === 'string' && item.specification" class="meta">{{ item.specification }}</p>
        <p v-else-if="item.propertyValueIds" class="meta">规格编号 {{ item.propertyValueIds }}</p>
        <p class="meta"><span :class="{ unavailable: item.stock === 0 }">{{ stockText(item.stock) }}</span></p>
        <p v-if="reasons(item)" class="reason">{{ reasons(item) }}</p>
        <span class="delivery-copy">查看规格与购买选项 →</span>
        </div>
      </button>
    </article>
    <p v-if="!list.length" class="empty">暂无可展示的商品</p>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import ProductImage from '@/components/common/ProductImage.vue';
import { money } from '@/utils/assistant';
import { ownerKey, session } from '@/api/client';
import { recommendationTouch, reportClick, reportExposure, type RecommendationTouch } from '@/api/traffic';
const props = defineProps<{ list: Record<string, any>[] }>();
const emit = defineEmits<{ select: [item: Record<string, any>] }>();
const container = ref<HTMLElement>();
const owner = computed(() => session.value ? ownerKey(session.value.actor) : '');
const visible = new Map<Element, RecommendationTouch>();
const exposed = new Set<string>(); const pending = new Set<string>(); const clicked = new Set<string>(); const clicking = new Set<string>();
const touchKey = (touch: RecommendationTouch) => `${touch.recommendation_id}:${touch.position}`;
let observer: IntersectionObserver | undefined; let revision = 0;
function recordVisible() {
  if (document.visibilityState !== 'visible' || !owner.value) return;
  const requestedOwner = owner.value;
  const groups = new Map<string, Set<number>>();
  for (const touch of visible.values()) {
    const key = touchKey(touch);
    if (exposed.has(key) || pending.has(key)) continue;
    pending.add(key);
    if (!groups.has(touch.recommendation_id)) groups.set(touch.recommendation_id, new Set());
    groups.get(touch.recommendation_id)!.add(touch.position);
  }
  for (const [id, positions] of groups) {
    void reportExposure(id, [...positions]).then((success) => {
      for (const position of positions) {
        const key = touchKey({ recommendation_id: id, position });
        if (success && requestedOwner === owner.value) exposed.add(key);
        pending.delete(key);
      }
    });
  }
}
async function observeCards() {
  const current = ++revision; observer?.disconnect(); visible.clear();
  await nextTick();
  if (current !== revision || !container.value || typeof IntersectionObserver === 'undefined') return;
  const receipts = new Map<Element, RecommendationTouch>();
  observer = new IntersectionObserver((entries) => {
    if (current !== revision) return;
    for (const entry of entries) {
      const receipt = receipts.get(entry.target);
      if (receipt && entry.isIntersecting && entry.intersectionRatio >= 0.5) visible.set(entry.target, receipt);
      else visible.delete(entry.target);
    }
    recordVisible();
  }, { threshold: 0.5 });
  container.value.querySelectorAll('article').forEach((element, index) => {
    const touch = recommendationTouch(props.list[index] || {});
    if (touch) { receipts.set(element, touch); observer!.observe(element); }
  });
}
async function select(item: Record<string, any>) {
  const requestedOwner = owner.value;
  const touch = recommendationTouch(item);
  if (!touch) { emit('select', item); return; }
  const key = touchKey(touch);
  if (clicking.has(key)) return;
  clicking.add(key);
  try {
    if (!clicked.has(key) && await reportClick(touch)) clicked.add(key);
    if (requestedOwner === owner.value) emit('select', item);
  } finally { clicking.delete(key); }
}
const reasons = (item: Record<string, any>) => Array.isArray(item.reasons) ? item.reasons.filter((reason: unknown) => typeof reason === 'string').join(' · ') : String(item.reason || '');
watch(() => [props.list, owner.value], observeCards);
onMounted(() => { void observeCards(); document.addEventListener('visibilitychange', recordVisible); });
onUnmounted(() => { revision++; observer?.disconnect(); visible.clear(); document.removeEventListener('visibilitychange', recordVisible); });
const priceText = (item: Record<string, any>) => {
  const price = item.price ?? item.minPrice;
  return price == null || !Number.isFinite(Number(price)) ? '价格待核实' : `¥${Number(price).toFixed(2)}`;
};
const stockText = (stock: unknown) => typeof stock !== 'number' ? '请选择规格核对库存' : stock > 0 ? `查询时库存 ${stock}` : '查询时无货';
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.agent-products {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  max-height: 420px;
  overflow-y: auto;
}

.product-tile {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 0;
  padding: 0;
  border: 1px solid $color-border;
  border-radius: 18px;
  background: $color-card;
  overflow: hidden;
  box-shadow: $shadow-xs;
}

.product-link {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  text-decoration: none;
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
  font: inherit;

  &:hover {
    background: transparent;
  }

  &:hover .tile-cover {
    transform: scale(1.02);
  }

  .tile-cover {
    display: block;
    width: 100%;
    border-radius: 0;
    transition: transform $transition-normal;
  }

  .tile-body {
    display: grid;
    gap: 6px;
    padding: 14px 14px 16px;
  }

  .name {
    margin: 0;
    font-size: 15px;
    line-height: 1.4;
    color: $color-text-title;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .title-row {
    display: flex;
    align-items: flex-start;
    gap: 5px;
    min-width: 0;

    .name {
      flex: 1;
    }
  }

  .price {
    margin: 0;
    font-size: 17px;
    font-weight: 650;
    color: $color-price;
    font-family: $font-display;
  }

  .delivery-copy {
    margin: 4px 0 0;
    color: $color-primary;
    font-size: 12px;
    line-height: 1.35;
  }

  .meta {
    display: flex;
    gap: 8px;
    justify-content: space-between;
    margin: 0;
    font-size: 12px;
    color: $color-text-muted;

    .unavailable {
      color: $color-error;
    }
  }

  .reason {
    margin: 0;
    overflow: hidden;
    color: $color-text-secondary;
    font-size: 11px;
    line-height: 1.3;
    text-overflow: ellipsis;
    white-space: nowrap;
  }


}

.empty {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 12px;
  color: $color-text-muted;
  text-align: center;
}
</style>
