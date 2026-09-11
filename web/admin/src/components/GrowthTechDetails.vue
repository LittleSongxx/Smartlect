<template>
  <details class="growth-tech">
    <summary>{{ title }}</summary>
    <pre>{{ json(value) }}</pre>
  </details>
</template>
<script setup>
import { json } from '../utils/growthDisplay'
defineProps({
  title: { type: String, default: '技术详情' },
  value: { type: [Object, Array, String, Number, Boolean], default: null },
})
</script>
