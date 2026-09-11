<template>
  <section v-if="ads.length" class="home-promotions" :class="variant" aria-labelledby="home-promotion-title">
    <header class="home-promotions-head">
      <div>
        <h3 id="home-promotion-title">商家推广 <span class="ad-label">广告</span></h3>
        <p>商家投放商品，与店内选品分开。点开前会登记模拟推广费用。</p>
      </div>
    </header>
    <div class="home-promotions-grid">
      <PromotionCard
        v-for="item in ads"
        :key="`${owner}:${revision}:${item.creative_id}`"
        :item="item"
        @select="select"
        @refresh="load"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { watch } from 'vue';
import { useRouter } from 'vue-router';
import PromotionCard from '@/components/PromotionCard.vue';
import { usePromotions } from '@/composables/usePromotions';
import type { Promotion } from '@/api/traffic';

withDefaults(defineProps<{ variant?: 'mobile' | 'desktop' }>(), { variant: 'mobile' });

const router = useRouter();
const { ads, owner, revision, load } = usePromotions(2);

watch(owner, (value) => { void (value ? load() : Promise.resolve(ads.value = [])); }, { immediate: true });

async function select(item: Promotion) {
  await router.push({
    path: '/catalog',
    query: { product: String(item.productId), sku: String(item.propertyValueIds || '') }
  });
}

defineExpose({ refresh: load });
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.home-promotions {
  min-width: 0;
}

.home-promotions.mobile {
  margin: 12px $app-page-gutter 0;
  padding: 16px 12px 14px;
  background: $color-card;
  border-radius: $radius-card;
  box-shadow: $shadow-card;
}

.home-promotions.desktop {
  width: $content-max-width;
  margin: 16px auto 0;
  padding: 16px 16px 18px;
  background: #fff;
  box-sizing: border-box;
}

.home-promotions-head {
  margin-bottom: 14px;
}

.home-promotions-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: $color-text-title;
  line-height: 1.3;
}

.home-promotions-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: $color-text-muted;
}

.ad-label {
  margin-left: 6px;
  border: 1px solid #d8c4a4;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 500;
  color: #9a5b2e;
  vertical-align: middle;
}

.home-promotions-grid {
  display: grid;
  gap: 10px;
}

.home-promotions.mobile .home-promotions-grid {
  grid-template-columns: 1fr;
}

.home-promotions.desktop .home-promotions-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.home-promotions.mobile :deep(.promotion-card) {
  padding: 14px;
  border-radius: 16px;
}

.home-promotions.mobile :deep(.promotion-product h3) {
  font-size: 16px;
}

.home-promotions.mobile :deep(.promotion-copy) {
  font-size: 13px;
}
</style>
