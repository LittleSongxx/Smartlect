<template>
  <div class="page-heading">
    <div class="page-heading__main">
      <h2 class="page-heading__title">{{ title }}</h2>
      <p v-if="description" class="page-heading__desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-heading__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<style scoped lang="scss">
// 页头卡片：全站每页的固定开头（标题 + 一句职责说明 + 右侧主操作），
// 规格与 web/shared/design-tokens.scss 的 @mixin page-heading 一致（Smartore 口径）。
.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 12px;
  padding: 20px 22px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--card-radius);

  &__main {
    min-width: 0;
  }

  &__title {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    line-height: 1.3;
    color: var(--text);
  }

  &__desc {
    margin: 8px 0 0;
    font-size: 13px;
    line-height: 1.6;
    color: var(--text-2);
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
}

@media (max-width: 720px) {
  .page-heading {
    flex-wrap: wrap;
    padding: 16px;
  }
}
</style>
