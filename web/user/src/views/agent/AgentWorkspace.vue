<template>
  <div class="agent-workspace" :class="{ compact }">
    <header v-if="!compact" class="chat-header">
      <div>
        <h2>导购与客服</h2>
        <p>{{ connection }}</p>
        <p v-if="capability" class="capability">{{ capability }}</p>
      </div>
      <div class="actions-inline">
        <button type="button" :disabled="busy" @click="restore()">刷新会话</button>
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
    <div v-else-if="conversationId" class="human-entry"><button type="button" :disabled="busy" @click="requestHandoff">需要人工协助</button></div>
    <AgentChatList />
    <AgentSendPanel />
  </div>
</template>
<script setup lang="ts">
import { computed, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import AgentChatList from '@/views/agent/AgentChatList.vue';
import AgentSendPanel from '@/views/agent/AgentSendPanel.vue';
import { HANDOFF_SYNC_INTERVAL_MS, useAgentSession } from '@/composables/useAgentSession';
import { ownerKey, session } from '@/api/client';
import { skillBanner } from '@/utils/agentDecision';

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });

const route = useRoute();
const { busy, error, connection, pending, conversationId, handoff, requestHandoff, restore, newConversation, send, syncConversation, visibleRuns } = useAgentSession();
const capability = computed(() => {
  const run = [...visibleRuns.value].reverse().find((item) => item.result?.decision || item.result?.skill_versions);
  return skillBanner(run?.result?.decision || (run?.result?.skill_versions ? { skill_versions: run.result.skill_versions, model_mode: run.model_mode, prompt_version: run.result.prompt_version } : null));
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
  align-items: flex-start;
  gap: 16px;
  padding: 20px 24px 16px;
  border-bottom: 1px solid $color-border-light;
}

.chat-header h2 {
  margin: 0;
  font-size: 22px;
  letter-spacing: 0;
}

.chat-header p {
  margin: 6px 0 0;
  color: $color-text-muted;
  font-size: 12px;
}

.capability {
  max-width: 36em;
  overflow-wrap: anywhere;
}

.actions-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.actions-inline button,
.human-entry button {
  white-space: nowrap;
  padding: 8px 14px;
  font-size: 13px;
  border-radius: $radius-btn;
}

.human-entry {
  display: flex;
  justify-content: flex-end;
  padding: 8px 24px 0;
}

.human-entry button {
  border: 0;
  color: $color-text-muted;
  background: transparent;
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
    padding: 6px 14px 0;
  }

  .notice {
    margin: 8px 12px 0;
    padding: 10px 12px;
  }

  :deep(.agent-welcome) {
    margin: 28px auto;
    padding: 0 12px;
  }

  :deep(.welcome-mark) {
    width: 56px;
    height: 56px;
    border-radius: 18px;
    font-size: 26px;
  }

  :deep(.agent-welcome h1) {
    font-size: 22px;
    margin: 16px 0 8px;
  }

  :deep(.agent-welcome p),
  :deep(.welcome-features) {
    font-size: 13px;
  }

  :deep(.agent-chat-list) {
    padding: 14px 16px;
  }

  :deep(.agent-composer-stack) {
    padding: 12px 14px;
  }
}

:deep(.agent-welcome) {
  max-width: 560px;
  text-align: center;
  margin: 48px auto;
  padding: 0 16px;
}

:deep(.welcome-mark) {
  display: inline-grid;
  place-items: center;
  width: 72px;
  height: 72px;
  border-radius: 24px;
  background: $color-primary;
  color: #fff;
  font-size: 34px;
  font-weight: 650;
}

:deep(.agent-welcome h1) {
  font-size: clamp(26px, 3vw, 34px);
  letter-spacing: 0;
  margin: 22px 0 12px;
  line-height: 1.35;
}

:deep(.agent-welcome p),
:deep(.welcome-features) {
  color: $color-text-muted;
  font-size: 15px;
  line-height: 1.7;
}

:deep(.welcome-features) {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px 18px;
  margin-top: 28px;
  font-size: 12px;
}

:deep(.agent-chat-list) {
  flex: 1;
  min-height: 0;
  padding: 20px 24px;
  overflow-y: auto;
}

:deep(.agent-composer-stack) {
  flex-shrink: 0;
}

:deep(.quick-tips) {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.tip-chip),
:deep(.btn-send-native) {
  white-space: nowrap;
}

:deep(.btn-send-native) {
  min-width: 88px;
  height: 44px;
  padding: 0 20px;
  border: 0;
  border-radius: 12px;
  background: $color-primary;
  color: #fff;
}
</style>
