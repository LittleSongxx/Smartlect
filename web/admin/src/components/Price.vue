<template>
  <div class="price">
    <div class="tag" :style="{ 'font-size': `${size * 0.8}px` }">￥</div>
    <div class="value" :style="{ 'font-size': `${size}px` }">{{ formatted }}</div>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance } from 'vue'

const props = defineProps({
  price: {
    type: Number,
  },
  size: {
    type: Number,
    default: 14,
  },
})

const formatted = computed(() => {
  const utils = getCurrentInstance()?.proxy?.Utils
  if (utils?.convert2Amount) return utils.convert2Amount(props.price)
  const value = Number(props.price)
  return Number.isFinite(value) ? value.toFixed(2) : '0.00'
})
</script>

<style lang="scss" scoped>
.price {
  display: flex;
  color: #ff0f23;
  font-weight: bold;
  align-items: flex-end;
}
</style>
