<template>
  <details v-if="decision" class="decision-card">
    <summary>本轮如何决定</summary>
    <p v-if="banner" class="muted">{{ banner }}</p>
    <p v-if="requestKind">声明：{{ requestKind }}</p>
    <p v-if="evidence">本轮证据：{{ evidence }}</p>
    <p v-if="compiled">编译结果：{{ compiled }}</p>
    <p v-if="tools">本轮工具：{{ tools }}</p>
    <p v-if="waitReason">等待原因：{{ waitReason }}</p>
    <p v-if="budget">预算：{{ budget }}</p>
    <ul v-if="checks.length">
      <li v-for="item in checks" :key="item.id">{{ checkText(item.id) }} · {{ checkStatusText(item.status) }}</li>
    </ul>
  </details>
</template>
<script setup>
import { computed } from 'vue';
import {
  answerStatusText,
  checkStatusText,
  checkText,
  evidenceKindText,
  requestKindText,
  skillBanner,
} from '../utils/growthDisplay';
const props = defineProps({
  decision: { type: Object, default: null },
  checks: { type: Array, default: () => [] },
});
const decision = computed(() => props.decision);
const checks = computed(() => (Array.isArray(props.checks) ? props.checks : []));
const banner = computed(() => skillBanner(decision.value));
const requestKind = computed(() => requestKindText(decision.value?.request_kind));
const evidence = computed(() => evidenceKindText(decision.value?.evidence_kind));
const compiled = computed(() => answerStatusText(decision.value?.compiled_answer_status || decision.value?.answer_status));
const tools = computed(() => (decision.value?.accepted_tools || []).join('、'));
const waitReason = computed(() => decision.value?.wait_reason || '');
const budget = computed(() => {
  const item = decision.value?.budget;
  if (!item) return '';
  const parts = [];
  if (item.model_attempts_limit != null) parts.push(`模型 ${item.model_attempts_used ?? 0}/${item.model_attempts_limit}`);
  if (item.tool_calls_limit != null) parts.push(`工具 ${item.tool_calls_used ?? 0}/${item.tool_calls_limit}`);
  if (item.retrieval_calls_limit != null) parts.push(`检索 ${item.retrieval_calls_used ?? 0}/${item.retrieval_calls_limit}`);
  return parts.join(' · ');
});
</script>
