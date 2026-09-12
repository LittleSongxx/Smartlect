<template>
  <div class="compare-wrap">
    <div class="compare-table" role="table" aria-label="商品对照">
      <div class="compare-row is-head" role="row">
        <span class="compare-label" role="columnheader">项目</span>
        <span v-for="column in columns" :key="column.sku_key" class="compare-cell" role="columnheader">
          {{ column.productName || column.sku_key }}
        </span>
      </div>
      <div v-for="row in rows" :key="row.field" class="compare-row" role="row" :class="{ differ: row.differ }">
        <span class="compare-label" role="rowheader">{{ row.label || row.field }}</span>
        <span v-for="column in columns" :key="column.sku_key" class="compare-cell" role="cell">
          {{ display(row, column.sku_key) }}
        </span>
      </div>
    </div>
    <p v-if="!complete" class="compare-incomplete">对照目标未齐，未用其它商品补位。</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { money } from '@/utils/assistant';

const props = defineProps<{
  comparison: Record<string, any>;
  complete?: boolean;
}>();

const columns = computed(() => {
  const listed = Array.isArray(props.comparison?.columns) ? props.comparison.columns : [];
  if (listed.length) return listed;
  return (props.comparison?.sku_keys || []).map((sku_key: string) => ({ sku_key }));
});
const rows = computed(() => Array.isArray(props.comparison?.rows) ? props.comparison.rows : []);
const complete = computed(() => props.complete !== false);

function display(row: Record<string, any>, skuKey: string) {
  const value = row?.values?.[skuKey];
  if (row.field === 'price_cents') return money(value);
  if (value == null || value === '') return '—';
  return String(value);
}
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.compare-wrap {
  margin: 12px 0 4px;
  overflow-x: auto;
}

.compare-table {
  min-width: 100%;
  border: 1px solid $color-border-light;
  border-radius: 10px;
  background: $color-bg-subtle;
}

.compare-row {
  display: grid;
  grid-template-columns: 72px repeat(auto-fit, minmax(96px, 1fr));
  gap: 0;
  border-top: 1px solid $color-border-light;

  &:first-child {
    border-top: 0;
  }

  &.is-head {
    font-weight: 600;
    color: $color-emphasis;
    background: $color-card;
  }

  &.differ .compare-cell {
    color: $color-primary;
  }
}

.compare-label,
.compare-cell {
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}

.compare-label {
  color: $color-text-muted;
  background: $color-card;
}

.compare-incomplete {
  margin: 8px 0 0;
  font-size: 12px;
  color: $color-text-muted;
}
</style>
