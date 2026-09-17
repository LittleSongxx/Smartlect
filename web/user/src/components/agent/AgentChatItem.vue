<template>
  <div class="bubble-row ai" role="article" aria-label="智能客服回复" :aria-busy="waiting">
    <div class="ai-avatar-mini"><el-icon :size="16"><Service /></el-icon></div>
    <div class="bubble ai-bubble is-wide">
      <p v-if="waiting && !data.result?.answer" class="typing">正在查询并整理回复…</p>
      <div v-if="uncovered" class="refuse-card" role="status">
        <p>资料未覆盖这一件。可以改问全店运费或退换，也可以转人工核实。</p>
        <div class="refuse-actions">
          <button type="button" @click="setGlobal">改问全店</button>
          <button type="button" :disabled="busy || Boolean(handoff)" @click="requestHandoff">转人工</button>
        </div>
      </div>
      <MarkdownContent v-else-if="citedAnswer" :content="citedAnswer" cite-marks />
      <p v-if="data.result?.answer_status === 'insufficient' && !uncovered" class="empty-hint">当前信息不足，请补充需求或等待人工核实。</p>
      <p v-if="['conflicting', 'needs_human'].includes(data.result?.answer_status)" class="empty-hint">该问题需要人工核实，当前不会继续自动执行。</p>
      <p v-if="data.result?.ticket" class="muted">已为您提交人工核实，可刷新会话查看客服回复。</p>
      <AgentCompareTable v-if="data.result?.comparison" :comparison="data.result.comparison" :complete="data.result.comparison_complete !== false" />
      <AgentProductList v-if="data.result?.products?.length" :list="data.result.products" @select="selectProduct" />
      <AgentOrderList v-if="data.result?.orders?.length" :list="data.result.orders" />
      <AgentConfirmCard v-if="data.result?.proposal" :card="data.result.proposal" @updated="(proposal) => emit('proposal-updated', proposal)" />
      <AgentDecisionCard :decision="data.result?.decision" :checks="data.result?.checks" />
      <ol v-if="sources.length" class="cite-list" aria-label="参考来源">
        <li v-for="source in sources" :key="source.index">
          <span class="cite-index">[{{ source.index }}]</span>
          <span class="cite-title">{{ source.title }}</span>
        </li>
      </ol>
      <p v-if="data.state === 'FAILED'" class="interrupt-tip" role="alert">{{ data.result?.proposal ? '本次助手运行中断，已保存的交易提案仍按上方状态处理。' : errorText(new Error(data.result?.error || '本次处理未完成，请补充问题或稍后重试。')) }}</p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { Service } from '@element-plus/icons-vue';
import MarkdownContent from '@/components/common/MarkdownContent.vue';
import AgentCompareTable from '@/components/agent/AgentCompareTable.vue';
import AgentProductList from '@/components/agent/AgentProductList.vue';
import AgentOrderList from '@/components/agent/AgentOrderList.vue';
import AgentConfirmCard from '@/components/agent/AgentConfirmCard.vue';
import AgentDecisionCard from '@/components/agent/AgentDecisionCard.vue';
import { errorText, type Proposal, type Run } from '@/api/client';
import { useAgentFocus } from '@/composables/useAgentFocus';
import { useAgentSession } from '@/composables/useAgentSession';
import { annotateAnswerWithCitations, displayCitations } from '@/utils/citations';
const props = defineProps<{ data: Run; waiting?: boolean }>();
const emit = defineEmits<{ 'proposal-updated': [proposal: Proposal] }>();
const router = useRouter();
const { setGlobal } = useAgentFocus();
const { busy, handoff, requestHandoff } = useAgentSession();
const sources = computed(() => displayCitations(props.data.result?.citations || []));
const citedAnswer = computed(() => annotateAnswerWithCitations(props.data.result?.answer || '', sources.value));
const uncovered = computed(() => props.data.result?.refuse_reason === 'product_uncovered'
  || (props.data.result?.answer_status === 'insufficient' && String(props.data.result?.answer || '').includes('资料未覆盖这一件')));
const selectProduct = (item: Record<string, any>) => {
  const query: Record<string, string> = {};
  if (item.propertyValueIds) query.sku = String(item.propertyValueIds);
  router.push({ path: `/product/${item.productId}`, query });
};
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.bubble-row.ai {
  display: flex;
  justify-content: flex-start;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 18px;
}

.bubble {
  width: fit-content;
  max-width: min(75%, 520px);
  padding: 14px 16px;
  font-size: 15px;
  line-height: 1.65;
  border-radius: 18px;
  word-break: break-word;
  flex: 0 1 auto;
  min-width: 0;
}

.ai-avatar-mini {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 11px;
  background: $color-primary;
  color: #fff;
  display: grid;
  place-items: center;
  box-shadow: none;
}

.ai-bubble {
  background: $color-card;
  color: $color-text-body;
  border: 1px solid $color-border-light;
  border-bottom-left-radius: 6px;
  box-shadow: $shadow-xs;

  &.is-wide {
    width: auto;
    max-width: calc(100% - 36px);
    flex: 1 1 auto;
    min-width: 0;
  }
}

.typing,
.interrupt-tip,
.empty-hint,
.muted {
  margin: 0;
  font-size: 13px;
  color: $color-text-muted;
}

.interrupt-tip {
  margin-top: 8px;
  font-size: 12px;
}

.empty-hint {
  line-height: 1.55;
}

.refuse-card {
  margin: 0 0 8px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid $color-warning-border;
  background: $color-warning-soft;
  color: #7a4b00;
}

.refuse-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
}

.refuse-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.refuse-actions button {
  padding: 6px 12px;
  border: 0;
  border-radius: 999px;
  background: rgba(122, 75, 0, 0.1);
  color: #7a4b00;
  font: inherit;
  font-size: 12px;
}

.cite-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid $color-border-light;
}

.cite-list li {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 0;
  padding: 3px 0;
  font-size: 12px;
  line-height: 1.5;
  color: $color-text-muted;
}

.cite-index {
  flex-shrink: 0;
  color: $color-primary;
  font-weight: 600;
}

.cite-title {
  min-width: 0;
}

:deep(.markdown-content) {
  font-size: 15px;
  line-height: 1.7;
  max-width: 100%;

  p {
    margin: 0;

    & + p {
      margin-top: 6px;
    }
  }
}

.ai-bubble:not(.is-wide) :deep(.markdown-content) {
  width: fit-content;
}

:deep(.agent-orders) {
  font-size: 12px;
}
</style>
