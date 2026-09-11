export const REQUEST_KIND_LABEL: Record<string, string> = {
  inquire_fact: '询问已发布事实',
  request_service: '要求未发布服务',
  request_exception: '要求例外裁决',
  request_handoff: '要求转交人工',
  clarify: '需要补充信息',
};

export const EVIDENCE_LABEL: Record<string, string> = {
  supported: '本轮有可见引用',
  none: '检索后合法空集',
  conflicting: '资料冲突',
  quarantined: '命中隔离资料',
  acl_denied: '当前身份不可见',
  unobserved: '本轮未检索',
};

export const ANSWER_STATUS_LABEL: Record<string, string> = {
  answered: '已答复',
  insufficient: '信息不足',
  conflicting: '资料冲突',
  needs_human: '转交人工',
};

export const CHECK_LABEL: Record<string, string> = {
  compiled_decision_present: '已记录编译输入',
  policy_grounding_has_this_turn_citation: '政策结论带本轮引用',
  no_business_claim_has_no_citations: '寒暄未携带证据',
  proposal_is_not_execution: '提案未当作已成交',
  needs_human_has_ticket: '转人工已建工单',
  budget_within_limits: '未超出本轮预算',
  model_has_no_tools: '经营模型未调用工具',
  no_replan_on_same_watermark: '无新观测不重新规划',
  evidence_bound_or_waiting: '计划绑定证据或等待授权',
};

export const CHECK_STATUS_LABEL: Record<string, string> = {
  passed: '通过',
  failed: '未通过',
  not_applicable: '本轮不适用',
};

export type DecisionSnapshot = {
  plane?: string;
  prompt_version?: string;
  schema_version?: string;
  skill_versions?: Record<string, string>;
  model_mode?: string;
  request_kind?: string;
  evidence_kind?: string;
  compiled_answer_status?: string;
  answer_status?: string;
  accepted_tools?: string[];
  citation_chunk_ids?: string[];
  proposal_id?: string | null;
  ticket_id?: string | null;
  wait_reason?: string;
  budget?: {
    model_attempts_used?: number;
    model_attempts_limit?: number;
    tool_calls_used?: number;
    tool_calls_limit?: number;
    retrieval_calls_used?: number;
    retrieval_calls_limit?: number;
  };
};

export type DecisionCheck = { id: string; status: string };

export function skillBanner(decision?: DecisionSnapshot | null) {
  if (!decision) return '';
  const skills = Object.entries(decision.skill_versions || {}).map(([name, version]) => `${name} ${version}`).join(' · ');
  return [decision.prompt_version, skills, decision.model_mode].filter(Boolean).join(' · ');
}

export function labeled(map: Record<string, string>, value?: string | null) {
  if (!value) return '';
  return map[value] || value;
}
