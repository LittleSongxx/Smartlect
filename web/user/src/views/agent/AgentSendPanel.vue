<template>
  <form class="agent-composer-stack" @submit.prevent="submit">
    <div v-if="hasTranscript" class="quick-tips">
      <button v-for="tip in tips" :key="tip" type="button" class="tip-chip" :disabled="busy" @click="input = tip">{{ tip }}</button>
    </div>
    <div class="composer-box">
      <div class="composer-top" role="group" aria-label="提问范围">
        <button
          v-if="productId"
          type="button"
          class="focus-chip"
          :class="{ active: focused }"
          :disabled="busy"
          @click="setProduct"
        >
          <span class="focus-dot" />
          正在问本商品{{ productName ? ` · ${shortName}` : '' }}
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
      <textarea
        ref="textarea"
        v-model="input"
        class="agent-chat-textarea"
        aria-label="输入咨询问题"
        :placeholder="composerPlaceholder"
        :disabled="busy || Boolean(handoff)"
        maxlength="8000"
        rows="1"
        @input="resize"
        @keydown="keydown"
      />
      <div class="composer-toolbar">
        <p class="composer-hint">下单和退款都会先确认，事实只依据当前可见资料。</p>
        <button type="submit" class="btn-send-native" :disabled="busy || Boolean(handoff) || !input.trim()">
          {{ busy ? '…' : '发送' }}
        </button>
      </div>
    </div>
  </form>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAgentFocus } from '@/composables/useAgentFocus';
import { useAgentSession } from '@/composables/useAgentSession';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';

const { busy, handoff, send, messages } = useAgentSession();
const { focused, productId, productName, tips, setGlobal, setProduct, payload } = useAgentFocus();
const panel = usePcAgentPanelStore();
const input = ref('');
const textarea = ref<HTMLTextAreaElement>();
const route = useRoute();
const hasTranscript = computed(() => messages.value.length > 0);
const shortName = computed(() => {
  const name = productName.value || '';
  return name.length > 12 ? `${name.slice(0, 12)}…` : name;
});
const composerPlaceholder = computed(() => {
  if (handoff.value) return '本会话已转人工，可刷新查看回复';
  return focused.value ? '问这件的成分、规格、包装或退换…' : '告诉我用途、预算，或咨询运费退换…';
});
function resize() {
  const el = textarea.value;
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
}
watch(
  () => panel.draft || (typeof route.query.draft === 'string' ? route.query.draft : ''),
  (draft) => {
    if (!draft) return;
    input.value = String(draft).slice(0, 8000);
    panel.draft = '';
    void nextTick(resize);
  },
  { immediate: true }
);
watch(input, () => void nextTick(resize));
async function submit() {
  const text = input.value;
  if (await send(text, false, payload())) {
    if (input.value === text) input.value = '';
    void nextTick(resize);
    textarea.value?.focus();
  }
}
function keydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  void submit();
}
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;

.agent-composer-stack {
  padding: 12px 16px 14px;
  background: $color-card;
}

.composer-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 12px 0;
}

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
  padding: 5px 10px;
  border-radius: $radius-pill;
}

.focus-chip.active {
  border-color: rgba($color-primary, 0.28);
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

.focus-hint {
  margin: 0;
  font-size: 12px;
  color: $color-text-muted;
}

.quick-tips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.tip-chip {
  border: 1px solid $color-border;
  background: $color-card;
  color: $color-text-body;
  font-size: 12px;
  padding: 5px 10px;
  border-radius: $radius-pill;

  &:hover:enabled {
    border-color: $color-primary;
    color: $color-primary;
    background: $color-primary-soft;
  }
}

.composer-box {
  border: 1px solid $color-border;
  border-radius: 16px;
  background: $color-card;
  transition: border-color $transition-fast, box-shadow $transition-fast;

  &:focus-within {
    border-color: rgba($color-primary, 0.35);
    box-shadow: 0 0 0 3px rgba($color-primary, 0.12);
  }
}

.agent-chat-textarea {
  display: block;
  width: 100%;
  min-width: 0;
  min-height: 36px;
  max-height: 120px;
  padding: 10px 12px 4px;
  border: 0;
  background: transparent;
  resize: none;
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  color: $color-text-title;

  &:focus {
    outline: none;
  }
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 8px 8px;
}

.composer-hint {
  margin: 0;
  flex: 1;
  min-width: 0;
  color: $color-text-muted;
  font-size: 11px;
  line-height: 1.4;
}

.btn-send-native {
  flex-shrink: 0;
  min-width: 64px;
  height: 32px;
  padding: 0 14px;
  border: 0;
  border-radius: $radius-pill;
  background: $color-primary;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;

  &:disabled {
    opacity: 0.4;
  }
}

@media (max-width: 640px) {
  .agent-composer-stack {
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0));
  }

  .composer-box {
    border-radius: 12px;
  }

  .agent-chat-textarea {
    font-size: 16px;
  }

  .composer-hint {
    display: none;
  }
}
</style>
