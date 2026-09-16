<template>
  <div class="detail-block">
    <div v-if="title" class="detail-block__title">{{ title }}</div>
    <pre v-if="hasContent" class="detail-text">{{ normalized }}</pre>
    <div v-else class="detail-block__empty">{{ emptyText }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  text: { type: [String, Object, Array, Number, Boolean], default: null },
  emptyText: { type: String, default: '暂无数据' },
})

const hasContent = computed(() => {
  if (props.text === null || props.text === undefined || props.text === '') return false
  if (typeof props.text === 'object' && Object.keys(props.text).length === 0) return false
  return true
})

const normalized = computed(() =>
  typeof props.text === 'string' ? props.text : JSON.stringify(props.text, null, 2),
)
</script>

<style scoped lang="scss">
.detail-block {
  min-width: 0;

  &__title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text2);
    margin: 8px 0 6px;
  }

  &__empty {
    font-size: 13px;
    color: var(--text3);
    padding: 8px 0;
  }
}

.detail-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0;
  padding: 12px;
  background: var(--detail-bg);
  border-radius: var(--card-radius);
  font-size: var(--detail-fs);
  font-family: var(--mono-font);
  line-height: 1.6;
  max-height: 360px;
  overflow: auto;
  color: var(--text2);
}
</style>
