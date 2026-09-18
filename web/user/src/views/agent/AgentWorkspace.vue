<template>
  <div class="agent-workspace" :class="{ compact }">
    <header v-if="!compact" class="chat-header">
      <div>
        <h2>{{ focused ? '问这件' : '导购与客服' }}</h2>
        <p>{{ headerHint }}</p>
      </div>
      <div class="actions-inline">
        <button type="button" :disabled="busy" @click="restore()">刷新</button>
        <button type="button" :disabled="busy" @click="newConversation">新会话</button>
      </div>
    </header>
    <div v-if="error" class="notice error" role="alert">{{ error }}
      <button v-if="pending" type="button" :disabled="busy" @click="send(pending.text, true)">用原消息编号重试</button>
    </div>
    <div v-if="handoff" class="notice" role="status">
      {{ handoff.status === 'TAKEN_OVER' ? '人工客服已接管本会话' : '本会话已提交人工处理' }} · 工单 {{ handoff.ticket_id }}。处理期间AI不会继续执行。
      <button type="button" :disabled="busy" @click="restore()">刷新回复</button>
    </div>
    <div v-else-if="conversationId && messages.length" class="human-entry"><button type="button" :disabled="busy" @click="requestHandoff">需要人工协助</button></div>
    <AgentChatList />
    <AgentSendPanel />
  </div>
</template>
<script setup lang="ts">
import { computed, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import AgentChatList from '@/views/agent/AgentChatList.vue';
import AgentSendPanel from '@/views/agent/AgentSendPanel.vue';
import { useAgentFocus } from '@/composables/useAgentFocus';
import { HANDOFF_SYNC_INTERVAL_MS, useAgentSession } from '@/composables/useAgentSession';
import { ownerKey, session } from '@/api/client';

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });

const route = useRoute();
const { focused } = useAgentFocus();
const { busy, error, connection, pending, conversationId, messages, handoff, requestHandoff, restore, newConversation, send, syncConversation } = useAgentSession();
const statusLine = computed(() => {
  const text = connection.value;
  if (!text || ['可以开始对话', '已从服务器恢复', '事件已连接'].includes(text)) return '';
  return text;
});
const headerHint = computed(() => {
  if (statusLine.value) return statusLine.value;
  return focused.value ? '当前只答这件商品和店规。想问其他请点「改问全店」。' : '当前按全店政策回答。';
});
function requestedConversation() {
  const value = route.query.conversation;
  return typeof value === 'string' ? value.trim() : '';
}
watch(() => [session.value ? ownerKey(session.value.actor) : '', requestedConversation()] as const, ([owner, requested]) => {
  if (owner && !busy.value) void restore(requested || undefined);
}, { immediate: true });

let syncTimer: number | undefined;
function stopHandoffSync() {
  if (syncTimer) {
    window.clearInterval(syncTimer);
    syncTimer = undefined;
  }
}
function startHandoffSync() {
  stopHandoffSync();
  syncTimer = window.setInterval(() => {
    if (document.hidden || busy.value || !handoff.value) return;
    void syncConversation();
  }, HANDOFF_SYNC_INTERVAL_MS);
}
function onVisibility() {
  if (document.hidden || busy.value) return;
  if (handoff.value?.status === 'OPEN' || handoff.value?.status === 'TAKEN_OVER') void syncConversation();
}
watch(() => handoff.value?.status, (status) => {
  if (status === 'OPEN' || status === 'TAKEN_OVER') startHandoffSync();
  else stopHandoffSync();
}, { immediate: true });
document.addEventListener('visibilitychange', onVisibility);
onUnmounted(() => {
  stopHandoffSync();
  document.removeEventListener('visibilitychange', onVisibility);
});
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;

.agent-workspace {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  flex: 1;
  word-break: normal;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid $color-border-light;
}

.chat-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0;
}

.chat-header p {
  margin: 4px 0 0;
  color: $color-text-muted;
  font-size: 12px;
}

.actions-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.actions-inline button,
.human-entry button {
  white-space: nowrap;
  padding: 6px 10px;
  font-size: 12px;
  border: 0;
  border-radius: $radius-btn;
  background: transparent;
  color: $color-text-muted;
}

.actions-inline button:hover:enabled,
.human-entry button:hover:enabled {
  color: $color-text-title;
  background: $color-bg-subtle;
}

.human-entry {
  display: flex;
  justify-content: flex-end;
  padding: 4px 16px 0;
}

.notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin: 10px 18px 0;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid $color-success-border;
  background: $color-success-soft;
  color: #24553a;
  font-size: 13px;
}

.notice button {
  margin-left: auto;
  padding: 4px 10px;
  border: 0;
  border-radius: 8px;
  background: rgba(36, 85, 58, .08);
  color: #24553a;
  font-size: 12px;
}

.notice.error {
  border-color: $color-error-border;
  background: $color-error-soft;
  color: #8a1c14;
}

.compact {
  .human-entry {
    padding: 4px 12px 0;
  }

  .notice {
    margin: 8px 12px 0;
    padding: 10px 12px;
  }

  :deep(.agent-chat-list) {
    padding: 16px 14px;
  }

  :deep(.agent-composer-stack) {
    padding: 10px 12px 12px;
  }
}

:deep(.agent-chat-list) {
  flex: 1;
  min-height: 0;
  padding: 16px;
  overflow-y: auto;
}

:deep(.agent-composer-stack) {
  flex-shrink: 0;
}
</style>
