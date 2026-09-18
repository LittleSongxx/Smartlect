<template>
  <div ref="chat" class="agent-chat-list" role="log" aria-label="会话内容" aria-live="polite">
    <div v-if="!messages.length && !orphanProposalRuns.length && !busy" class="agent-welcome">
      <div class="welcome-hero">
        <span class="welcome-mark" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path d="M8 10h8M8 14h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            <path d="M20.4 12a8.4 8.4 0 0 1-11.2 8L4.2 21l1.1-4.1A8.4 8.4 0 1 1 20.4 12Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
          </svg>
        </span>
        <h1>{{ focused ? '先问这件' : '开始对话' }}</h1>
        <p>{{ focused ? '现在只回答这件商品，以及适用的运费、退换等店规。想问其他商品、全店选品或订单，请先点下方「改问全店」。' : '当前是全店模式，可按店内政策帮你选购、查运费退换和本人订单。' }}</p>
      </div>
      <div class="welcome-cards">
        <button
          v-for="tip in tips"
          :key="tip"
          type="button"
          class="welcome-card"
          :disabled="busy"
          @click="fillTip(tip)"
        >
          <span class="welcome-card-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path :d="tipIcon(tip)" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span>{{ tip }}</span>
        </button>
      </div>
    </div>
    <template v-for="message in visibleMessages" :key="message.message_id">
      <AgentUserBubble v-if="message.role === 'user'" :user-message="displayMessage(message.content)" />
      <AgentChatItem v-if="message.agent_run_id && runs[message.agent_run_id] && !runs[message.agent_run_id]!.parent_run_id" :data="runs[message.agent_run_id]!" :waiting="['CREATED', 'RUNNING'].includes(runs[message.agent_run_id]!.state)" @proposal-updated="updateProposal" />
      <div v-if="message.role === 'assistant' && !message.agent_run_id" class="human-panel">
        <p class="eyebrow">人工客服</p>
        <MarkdownContent :content="message.content" />
      </div>
    </template>
    <AgentChatItem v-for="run in orphanProposalRuns" :key="run.agent_run_id" :data="run" @proposal-updated="updateProposal" />
    <p v-if="busy" class="processing" role="status">正在与服务端同步，请稍候…</p>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import AgentUserBubble from '@/components/agent/AgentUserBubble.vue';
import AgentChatItem from '@/components/agent/AgentChatItem.vue';
import MarkdownContent from '@/components/common/MarkdownContent.vue';
import { useAgentFocus } from '@/composables/useAgentFocus';
import { useAgentSession } from '@/composables/useAgentSession';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';

const { messages, runs, visibleRuns, busy, updateProposal } = useAgentSession();
const { focused, tips } = useAgentFocus();
const panel = usePcAgentPanelStore();
const chat = ref<HTMLElement>();
const visibleMessages = computed(() => messages.value.filter((message) =>
  (message.role === 'user' && (!message.agent_run_id || !runs.value[message.agent_run_id]?.parent_run_id)) ||
  (message.role === 'assistant' && !message.agent_run_id)));
const orphanProposalRuns = computed(() => visibleRuns.value.filter((run) => run.result?.proposal &&
  !messages.value.some((message) => message.role === 'user' && message.agent_run_id === run.agent_run_id)));
function displayMessage(text: string) {
  try { const value = JSON.parse(text); if (value.action_type && value.parameters) return `请求${({ order: '下单', cancel: '取消订单', refund: '退款' } as Record<string, string>)[value.action_type] || '操作'}确认`; } catch { /* normal prose */ }
  return text;
}
const TIP_ICONS: Record<string, string> = {
  运费怎么算: 'M3 7h13l5 6H8L3 7Zm5 6v5h10v-5',
  退换货政策: 'M4 12a8 8 0 1 0 2.3-5.7M4 4v5h5',
  帮我选一件: 'M12 3l2.2 6.6H21l-5.4 4 2.1 6.4L12 16.6 6.3 20l2.1-6.4L3 9.6h6.8L12 3Z',
  查询我的订单: 'M7 4h10v16H7V4Zm3 4h4M10 12h4M10 16h3',
  成分有哪些: 'M9 3h6M10 3v5l-5 9a4 4 0 0 0 3.5 6h7A4 4 0 0 0 19 17l-5-9V3',
  规格怎么选: 'M4 7h16M4 12h10M4 17h7M18 10v8M15 15l3 3 3-3',
  包装是什么样: 'M3 8l9-5 9 5v8l-9 5-9-5V8Zm9 5V3',
  这件怎么退: 'M4 12a8 8 0 1 0 2.3-5.7M4 4v5h5',
};
function tipIcon(tip: string) {
  return TIP_ICONS[tip] || 'M8 10h8M8 14h5M20.4 12a8.4 8.4 0 0 1-11.2 8L4.2 21l1.1-4.1A8.4 8.4 0 1 1 20.4 12Z';
}
function fillTip(tip: string) {
  panel.draft = '';
  void nextTick(() => { panel.draft = tip; });
}
watch(() => [messages.value.length, busy.value], async () => { await nextTick(); if (chat.value) chat.value.scrollTop = chat.value.scrollHeight; });
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;

.agent-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 28px;
  min-height: 100%;
  padding: 32px 8px 20px;
  text-align: center;
}

.welcome-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 28em;
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin-bottom: 10px;
  color: $color-text-3;
  opacity: 0.7;
}

.agent-welcome h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
  color: $color-text-title;
}

.agent-welcome p {
  margin: 6px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: $color-text-muted;
}

.welcome-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: min(100%, 420px);
}

.welcome-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid $color-border;
  border-radius: 14px;
  background: $color-card;
  color: $color-text-title;
  font-size: 13px;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: border-color $transition-fast, background $transition-fast, color $transition-fast;

  &:hover:enabled {
    border-color: rgba($color-primary, 0.45);
    background: $color-primary-soft;
    color: $color-primary;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.welcome-card-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 8px;
  background: $color-bg-subtle;
  color: $color-text-2;
}

.welcome-card:hover:enabled .welcome-card-icon {
  background: #fff;
  color: $color-primary;
}

.human-panel {
  max-width: min(85%, 560px);
  margin-bottom: 18px;
  padding: 12px 16px;
  border: 1px solid $color-border-light;
  border-radius: 16px;
  background: $color-card;
}

.eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  color: $color-text-muted;
}

.processing {
  margin: 8px 0 0;
  font-size: 13px;
  color: $color-text-muted;
}

@media (max-width: 640px) {
  .welcome-cards {
    grid-template-columns: 1fr;
    width: 100%;
  }
}
</style>
