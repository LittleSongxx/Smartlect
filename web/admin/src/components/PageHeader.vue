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
.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;

  &__main {
    min-width: 0;
  }

  &__title {
    margin: 0 0 4px;
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
  }

  &__desc {
    margin: 0;
    font-size: 13px;
    line-height: 1.6;
    color: var(--text3);
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
  }
}
</style>
