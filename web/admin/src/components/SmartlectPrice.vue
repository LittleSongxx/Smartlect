<template><span class="price"><span aria-hidden="true">¥</span>{{ money(price) }}</span></template>
<script setup>
import { money } from '../api/client';
defineProps({ price: Number });
</script>
<style scoped>.price { display: inline-flex; gap: 3px; font-weight: 650; align-items: baseline; font-variant-numeric: tabular-nums; }</style>
