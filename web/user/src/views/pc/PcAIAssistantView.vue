<template>
  <div class="pc-agent-page agent-page">
    <AgentWorkspace />
  </div>
</template>
<script setup lang="ts">
import AgentWorkspace from '@/views/agent/AgentWorkspace.vue';
</script>
<style scoped lang="scss">
.pc-agent-page {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
}
</style>
