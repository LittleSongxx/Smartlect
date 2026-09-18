<template>
  <button
    type="button"
    class="agent-service-entry"
    :class="{ compact }"
    :aria-label="entryLabel"
    @click="goAgent"
  >
    <el-icon :size="iconSize"><ChatDotRound /></el-icon>
    <span v-if="showLabel" class="label">{{ entryLabel }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ChatDotRound } from '@element-plus/icons-vue';
import { useOpenAgent } from '@/composables/useOpenAgent';
import type { AgentConsultProduct } from '@/utils/agentProductConsult';

const props = withDefaults(
  defineProps<{
    compact?: boolean;
    showLabel?: boolean;
    iconSize?: number;
    consultProduct?: AgentConsultProduct | null;
  }>(),
  {
    compact: true,
    showLabel: false,
    iconSize: 22,
    consultProduct: null
  }
);

const { openAgent } = useOpenAgent();
const entryLabel = computed(() => (props.consultProduct?.productId ? '问这件' : '导购'));

const goAgent = () => {
  openAgent({
    consultProduct: props.consultProduct,
    fromProduct: !!props.consultProduct?.productId
  });
};
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.agent-service-entry {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: $color-bg-subtle;
  color: $color-text-title;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;

  &.compact {
    width: 36px;
    height: 36px;
  }

  &:not(.compact) {
    min-height: 36px;
    padding: 0 12px;
    border-radius: $radius-pill;
  }

  .label {
    font-size: 13px;
    font-weight: 500;
  }
}
</style>
