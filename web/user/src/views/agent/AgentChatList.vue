<template>
  <div ref="chat" class="agent-chat-list" role="log" aria-label="会话内容" aria-live="polite">
    <div v-if="!messages.length && !orphanProposalRuns.length && !busy" class="agent-welcome">
      <span class="welcome-mark">S</span><h1>选择，从了解开始。</h1>
      <p>我是智选商城导购与客服助手。<br />一起选合适的商品，也可以只聊商品用法或售后政策。</p>
      <div class="welcome-features"><span>根据您的需求选购</span><span>知识回答附来源</span><span>交易由您确认</span></div>
    </div>
    <template v-for="message in visibleMessages" :key="message.message_id">
      <AgentUserBubble v-if="message.role === 'user'" :user-message="displayMessage(message.content)" />
      <AgentChatItem v-if="message.agent_run_id && runs[message.agent_run_id] && !runs[message.agent_run_id]!.parent_run_id" :data="runs[message.agent_run_id]!" :waiting="['CREATED', 'RUNNING'].includes(runs[message.agent_run_id]!.state)" @proposal-updated="updateProposal" />
      <div v-if="message.role === 'assistant' && !message.agent_run_id" class="panel"><p class="eyebrow">人工客服</p><MarkdownContent :content="message.content" /></div>
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
import { useAgentSession } from '@/composables/useAgentSession';
const { messages, runs, visibleRuns, busy, updateProposal } = useAgentSession();
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
watch(() => [messages.value.length, busy.value], async () => { await nextTick(); if (chat.value) chat.value.scrollTop = chat.value.scrollHeight; });
</script>
