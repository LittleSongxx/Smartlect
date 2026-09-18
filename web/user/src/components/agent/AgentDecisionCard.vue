<template>
  <details v-if="decision" class="decision">
    <summary>本轮如何决定</summary>
    <dl>
      <div v-if="requestKind"><dt>声明</dt><dd>{{ requestKind }}</dd></div>
      <div v-if="evidence"><dt>本轮证据</dt><dd>{{ evidence }}</dd></div>
      <div v-if="compiled"><dt>编译结果</dt><dd>{{ compiled }}</dd></div>
      <div v-if="tools"><dt>本轮工具</dt><dd>{{ tools }}</dd></div>
      <div v-if="budget"><dt>剩余预算</dt><dd>{{ budget }}</dd></div>
    </dl>
    <ul v-if="checks.length" class="checks" aria-label="确定性自检">
      <li v-for="item in checks" :key="item.id">{{ checkLabel(item.id) }} · {{ statusLabel(item.status) }}</li>
    </ul>
  </details>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import {
  ANSWER_STATUS_LABEL,
  CHECK_LABEL,
  CHECK_STATUS_LABEL,
  EVIDENCE_LABEL,
  REQUEST_KIND_LABEL,
  labeled,
  type DecisionCheck,
  type DecisionSnapshot,
} from '@/utils/agentDecision';

const props = defineProps<{ decision?: DecisionSnapshot | null; checks?: DecisionCheck[] }>();
const decision = computed(() => props.decision || null);
const checks = computed(() => (Array.isArray(props.checks) ? props.checks : []));
const requestKind = computed(() => labeled(REQUEST_KIND_LABEL, decision.value?.request_kind));
const evidence = computed(() => labeled(EVIDENCE_LABEL, decision.value?.evidence_kind));
const compiled = computed(() => labeled(ANSWER_STATUS_LABEL, decision.value?.compiled_answer_status || decision.value?.answer_status));
const tools = computed(() => (decision.value?.accepted_tools || []).join('、'));
const budget = computed(() => {
  const item = decision.value?.budget;
  if (!item) return '';
  const parts = [];
  if (item.model_attempts_limit != null) parts.push(`模型 ${item.model_attempts_used ?? 0}/${item.model_attempts_limit}`);
  if (item.tool_calls_limit != null) parts.push(`工具 ${item.tool_calls_used ?? 0}/${item.tool_calls_limit}`);
  if (item.retrieval_calls_limit != null) parts.push(`检索 ${item.retrieval_calls_used ?? 0}/${item.retrieval_calls_limit}`);
  return parts.join(' · ');
});
const checkLabel = (id: string) => CHECK_LABEL[id] || id;
const statusLabel = (status: string) => CHECK_STATUS_LABEL[status] || status;
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;

.decision {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid $color-border-light;
  font-size: 12px;
  color: $color-text-muted;
}

.decision summary {
  cursor: pointer;
  color: $color-text-muted;
  font-size: 12px;
  font-weight: 500;
}

.decision dl {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
}

.decision dl div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
}

.decision dt {
  margin: 0;
  color: $color-text-muted;
}

.decision dd {
  margin: 0;
  color: $color-text-body;
}

.checks {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
}

.checks li {
  padding: 2px 0;
}
</style>
