<template>
  <button ref="root" type="button" :disabled="clicking || unavailable" @click="onClick">
    <slot :clicking="clicking" :error="error" />
  </button>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import type { Promotion } from '@/api/traffic';
import { usePromotionCharge } from '@/composables/usePromotionCharge';

const props = defineProps<{ item: Promotion }>();
const emit = defineEmits<{ charged: [item: Promotion] }>();
const root = ref<HTMLElement>();
const { activate, observe, clicking, error, unavailable } = usePromotionCharge(() => props.item);

async function onClick() {
  if (await activate()) emit('charged', props.item);
}

onMounted(() => observe(root.value || null));
</script>

<style scoped>
button {
  font: inherit;
  color: inherit;
  text-align: inherit;
}
</style>
