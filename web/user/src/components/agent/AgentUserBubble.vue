<template>
  <div class="bubble-row user" role="article" aria-label="我的消息">
    <div class="bubble user-bubble"><p class="text">{{ userMessage }}</p></div>
  </div>
</template>
<script setup lang="ts">
defineProps<{ userMessage: string }>();
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.bubble-row.user {
  display: flex;
  justify-content: flex-end;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 18px;
}

.bubble {
  width: fit-content;
  max-width: min(75%, 520px);
  padding: 12px 16px;
  font-size: 15px;
  line-height: 1.6;
  border-radius: 18px;
  word-break: break-word;
  flex: 0 1 auto;
}

.user-bubble {
  background: $color-primary;
  color: #fffdf8;
  border-bottom-right-radius: 6px;

  .text {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
  }

}
</style>
