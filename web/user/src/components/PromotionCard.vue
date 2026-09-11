<template>
  <article ref="card" class="promotion-card" :aria-label="`${item.productName} 广告`">
    <div class="promotion-heading"><span class="promotion-label">广告 · 模拟推广</span><span>{{ item.specification }}</span></div>
    <div class="promotion-product"><ProductImage :product="item" :width="70" :height="70" /><div><h3>{{ item.productName }}</h3><p class="promotion-price">{{ money(item.price_cents) }}</p></div></div>
    <p class="promotion-copy">{{ item.copy_text }}</p><p v-if="item.reasons?.length" class="muted">{{ item.reasons.join(' · ') }}</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <button v-if="unavailable" type="button" @click="$emit('refresh')">刷新推广商品</button>
    <button v-else type="button" :disabled="clicking" @click="select">{{ clicking ? '正在打开…' : '查看推广商品 →' }}</button>
  </article>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue';
import ProductImage from '@/components/common/ProductImage.vue';
import { usePromotionCharge } from '@/composables/usePromotionCharge';
import { money } from '@/utils/assistant';
import type { Promotion } from '@/api/traffic';
const props = defineProps<{ item: Promotion }>();
const emit = defineEmits<{ select: [item: Promotion]; refresh: [] }>();
const card = ref<HTMLElement>();
const { activate, observe, clicking, error, unavailable } = usePromotionCharge(() => props.item);
async function select() {
  if (await activate()) emit('select', props.item);
}
onMounted(() => observe(card.value || null));
</script>
<style scoped>
.promotion-card { min-width: 0; background: #fffdf9; border: 1px solid #e4d9c8; padding: 22px; border-radius: 20px; display: flex; flex-direction: column; align-items: flex-start; overflow-wrap: anywhere; box-shadow: 0 1px 2px rgba(26, 23, 19, .04); }.promotion-heading { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; width: 100%; font-size: 11px; color: #7a7267; }.promotion-label { border: 1px solid #d8c4a4; border-radius: 999px; padding: 2px 8px; color: #9a5b2e; }.promotion-product { display: flex; gap: 16px; align-items: center; margin-top: 18px; }.promotion-product :deep(.product-image) { border-radius: 14px; }.promotion-product h3 { margin: 0; font-size: 20px; }.promotion-price { margin: 8px 0 0; font-weight: 650; color: #b24528; }.promotion-copy { white-space: pre-wrap; color: #4d473e; }.promotion-card button { margin-top: auto; border-radius: 999px; }.promotion-card .notice { width: 100%; }.promotion-card .muted { margin-top: 0; }
</style>
