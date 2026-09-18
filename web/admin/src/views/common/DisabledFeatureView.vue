<template>
  <div class="ai-page">
    <PageHeader :title="title" :description="detail" />
    <el-alert type="warning" show-icon :closable="false" title="此功能已停用">
      {{ detail }}
    </el-alert>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'

const route = useRoute()
const title = computed(() => route.meta.disabledTitle || '已停用')
const detail = computed(() => route.meta.disabledDetail || '此功能已停用。')
</script>

<style scoped>
.ai-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
