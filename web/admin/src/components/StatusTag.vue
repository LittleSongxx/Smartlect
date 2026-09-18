<template>
  <el-tag :type="tagType" :size="size" disable-transitions>{{ label }}</el-tag>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  // tone 是页面语义色（与 growthDisplay.badgeTone 对齐）：ok=成功 wait=进行/等待 warn=异常；也可直接传 el-tag type
  tone: { type: String, default: '' },
  size: { type: String, default: 'small' },
})

const TONE_TO_TAG = { ok: 'success', wait: 'info', warn: 'warning', danger: 'danger', info: 'info' }

const tagType = computed(() => TONE_TO_TAG[props.tone] || props.tone || 'info')
</script>
