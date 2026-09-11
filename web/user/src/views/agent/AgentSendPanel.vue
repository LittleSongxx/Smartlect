<template>
  <form class="agent-composer-stack" @submit.prevent="submit">
    <div class="quick-tips"><span class="tips-label">试着问</span>
      <button v-for="tip in tips" :key="tip" type="button" class="tip-chip" :disabled="busy" @click="input = tip">{{ tip }}</button>
    </div>
    <div class="chat-input-bar">
      <textarea ref="textarea" v-model="input" class="agent-chat-textarea" aria-label="输入咨询问题" :placeholder="handoff ? '本会话已转人工，可刷新查看回复' : '告诉我用途、预算，或咨询退换货政策…'" :disabled="busy || Boolean(handoff)" maxlength="8000" rows="2" @keydown="keydown" />
      <button type="submit" class="btn-send-native" :disabled="busy || Boolean(handoff) || !input.trim()">{{ busy ? '处理中…' : '发送' }}</button>
    </div>
    <p class="composer-hint">下单和退款都会先给您确认</p>
  </form>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAgentSession } from '@/composables/useAgentSession';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';
const { busy, handoff, send } = useAgentSession();
const panel = usePcAgentPanelStore();
const input = ref('');
const textarea = ref<HTMLTextAreaElement>();
const route = useRoute();
watch(
  () => panel.draft || (typeof route.query.draft === 'string' ? route.query.draft : ''),
  (draft) => { if (draft) input.value = String(draft).slice(0, 8000); },
  { immediate: true }
);
const tips = ['我想了解退换货政策', '帮我选一件适合日常使用的商品', '查询我的订单'];
async function submit() {
  const text = input.value;
  const extra: { product_id?: string; sku_key?: string } = {};
  const productId = panel.productId || (typeof route.query.product === 'string' ? route.query.product : '');
  const skuKey = panel.skuKey || (typeof route.query.sku === 'string' ? route.query.sku : '');
  if (productId) extra.product_id = productId;
  if (skuKey) extra.sku_key = skuKey;
  if (await send(text, false, extra)) { if (input.value === text) input.value = ''; textarea.value?.focus(); }
}
function keydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault(); void submit();
}
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;
.agent-composer-stack { border-top: 1px solid $color-border; padding: 16px 24px; background: $color-card; }
.quick-tips { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tips-label { font-size: 12px; color: $color-text-muted; }
.tip-chip { border: 1px solid rgba($color-primary, .2); background: $color-primary-soft; color: $color-primary; font-size: 12px; padding: 7px 12px; border-radius: $radius-pill; }
.chat-input-bar { display: flex; align-items: flex-end; gap: 10px; }
.agent-chat-textarea { flex: 1; min-width: 0; resize: vertical; max-height: 180px; border: 1px solid $color-border; border-radius: $radius-card; padding: 12px; font: inherit; line-height: 1.5; }
.btn-send-native { flex-shrink: 0; min-width: 88px; height: 44px; padding: 0 22px; border: 0; border-radius: 12px; background: $color-primary; color: #fff; font: inherit; white-space: nowrap; }
.composer-hint { margin: 8px 0 0; color: $color-text-muted; font-size: 11px; }
@media (max-width: 640px) { .agent-composer-stack { padding: 12px; } .tips-label { display: none; } .quick-tips { gap: 5px; } .tip-chip { font-size: 11px; padding: 6px 8px; } }
</style>
