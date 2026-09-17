<template>
  <form class="agent-composer-stack" @submit.prevent="submit">
    <div class="focus-bar" role="group" aria-label="提问范围">
      <button
        v-if="productId"
        type="button"
        class="focus-chip"
        :class="{ active: focused }"
        :disabled="busy"
        @click="setProduct"
      >
        <span class="focus-dot" />
        正在问本商品{{ productName ? ` · ${productName}` : '' }}
      </button>
      <button
        type="button"
        class="focus-chip"
        :class="{ active: !focused }"
        :disabled="busy"
        @click="setGlobal"
      >
        全店
      </button>
      <p v-if="!productId" class="focus-hint">当前按全店政策回答</p>
    </div>
    <div class="quick-tips"><span class="tips-label">试着问</span>
      <button v-for="tip in tips" :key="tip" type="button" class="tip-chip" :disabled="busy" @click="input = tip">{{ tip }}</button>
    </div>
    <div class="chat-input-bar">
      <textarea ref="textarea" v-model="input" class="agent-chat-textarea" aria-label="输入咨询问题" :placeholder="composerPlaceholder" :disabled="busy || Boolean(handoff)" maxlength="8000" rows="2" @keydown="keydown" />
      <button type="submit" class="btn-send-native" :disabled="busy || Boolean(handoff) || !input.trim()">{{ busy ? '处理中…' : '发送' }}</button>
    </div>
    <p class="composer-hint">下单和退款都会先给您确认。独特事实只依据当前可见资料。</p>
  </form>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAgentFocus } from '@/composables/useAgentFocus';
import { useAgentSession } from '@/composables/useAgentSession';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';
const { busy, handoff, send } = useAgentSession();
const { focused, productId, productName, tips, setGlobal, setProduct, payload } = useAgentFocus();
const panel = usePcAgentPanelStore();
const input = ref('');
const textarea = ref<HTMLTextAreaElement>();
const route = useRoute();
const composerPlaceholder = computed(() => {
  if (handoff.value) return '本会话已转人工，可刷新查看回复';
  return focused.value ? '问这件的成分、规格、包装或退换…' : '告诉我用途、预算，或咨询运费退换…';
});
watch(
  () => panel.draft || (typeof route.query.draft === 'string' ? route.query.draft : ''),
  (draft) => { if (draft) input.value = String(draft).slice(0, 8000); },
  { immediate: true }
);
async function submit() {
  const text = input.value;
  if (await send(text, false, payload())) { if (input.value === text) input.value = ''; textarea.value?.focus(); }
}
function keydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault(); void submit();
}
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;
.agent-composer-stack { border-top: 1px solid $color-border; padding: 16px 24px; background: $color-card; }
.focus-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.focus-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  border: 1px solid $color-border;
  background: $color-bg-subtle;
  color: $color-text-secondary;
  font-size: 12px;
  line-height: 1.3;
  padding: 6px 12px;
  border-radius: $radius-pill;
}
.focus-chip.active {
  border-color: rgba($color-primary, .28);
  background: $color-primary-soft;
  color: $color-primary;
  font-weight: 600;
}
.focus-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.focus-hint { margin: 0; font-size: 12px; color: $color-text-muted; }
.quick-tips { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tips-label { font-size: 12px; color: $color-text-muted; }
.tip-chip { border: 1px solid rgba($color-primary, .2); background: $color-primary-soft; color: $color-primary; font-size: 12px; padding: 7px 12px; border-radius: $radius-pill; }
.chat-input-bar { display: flex; align-items: flex-end; gap: 10px; }
.agent-chat-textarea { flex: 1; min-width: 0; resize: vertical; max-height: 180px; border: 1px solid $color-border; border-radius: $radius-card; padding: 12px; font: inherit; line-height: 1.5; }
.btn-send-native { flex-shrink: 0; min-width: 88px; height: 44px; padding: 0 22px; border: 0; border-radius: 12px; background: $color-primary; color: #fff; font: inherit; white-space: nowrap; }
.composer-hint { margin: 8px 0 0; color: $color-text-muted; font-size: 11px; }
@media (max-width: 640px) {
  .agent-composer-stack { padding: 12px; }
  .tips-label { display: none; }
  .quick-tips { gap: 5px; }
  .tip-chip { font-size: 11px; padding: 6px 8px; }
  .focus-chip { font-size: 11px; }
}
</style>
