<template>
  <svg
    class="brand-mark-svg"
    :class="rootClass"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 32 32"
    role="img"
    aria-label="Smartlect"
  >
    <defs>
      <linearGradient id="brand-cta" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--primary)" />
        <stop offset="100%" stop-color="var(--brand-yellow)" />
      </linearGradient>
    </defs>
    <rect x="2" y="2" width="28" height="28" rx="7" :fill="tileFill" />
    <path
      fill="none"
      :stroke="checkColor"
      stroke-width="2.7"
      stroke-linecap="round"
      stroke-linejoin="round"
      d="m8.8 16.2 4.7 4.7 9.7-10.1"
    />
    <path
      fill="none"
      :stroke="sparkColor"
      stroke-width="1.8"
      stroke-linecap="round"
      d="M9.4 7.1v4.2M7.3 9.2h4.2"
    />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rootClass: String,
  variant: {
    type: String,
    default: 'default',
  },
})

// 品牌渐变与 token 里的 --grad-cta 同源（淘宝橙 → 淘宝黄）。
// light 变体用于深色/图片背景：白底 + 橙勾。
const tileFill = computed(() => (props.variant === 'light' ? '#ffffff' : 'url(#brand-cta)'))
const checkColor = computed(() => (props.variant === 'light' ? 'var(--primary)' : '#ffffff'))
const sparkColor = computed(() => (props.variant === 'light' ? 'var(--brand-yellow)' : '#fff8dc'))
</script>

<style scoped>
.brand-mark-svg {
  display: block;
  flex-shrink: 0;
}
</style>
