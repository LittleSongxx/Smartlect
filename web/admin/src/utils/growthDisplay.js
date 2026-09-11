export const diagnosisLabels = {
  stockout: '已观察售罄',
  creative_underperforming: '素材表现',
  payment_failures: '权威支付尝试失败',
  refunds: '退款变化',
  insufficient_evidence: '证据不足',
  other: '其他观察',
}

export const statusText = (value) =>
  ({
    RUNNING: '运行中',
    WAIT_USER: '等待商家批准',
    WAIT_MERCHANT: '等待商家批准',
    WAIT_APPROVAL: '等待商家批准',
    WAIT_OUTCOME: '等待新结果',
    WAIT_OBSERVATION: '等待新观测',
    PARTIALLY_APPLIED: '部分执行，待核对',
    COMPLETED: '已完成本次任务',
    FAILED: '运行失败',
    DRAFT: '计划草稿',
    EXECUTING: '执行中',
    UNKNOWN: '状态待核对',
  })[value] || value || '尚未报告'

export const modeText = (value) =>
  ({
    live: '真实模型 live',
    mock: '模拟模型 mock',
    rule: '确定性规则',
    not_called: '未调用模型',
    'rule-fallback': '规则降级 rule-fallback',
  })[value] || value || '模式未知'

export const periodText = (value) =>
  ({
    scope_lifetime: '授权有效期内',
    campaign_lifetime: '活动有效期内',
    next_round: '下一轮观测前',
  })[value] || value || '未报告'

export const campaignStatusText = (value) =>
  ({
    DRAFT: '草稿',
    ACTIVE: '投放中',
    PAUSED: '已暂停',
    EXHAUSTED: '额度用尽',
    REVOKED: '已撤销',
  })[value] || value || '未知'

export const grantStatusText = (item) => {
  if (!item) return '未知'
  if (item.revoked_at || item.status === 'REVOKED') return '已撤销'
  return ({ APPROVED: '已批准', ACTIVE: '生效中', DRAFT: '待批准' })[item.status] || item.status || '已批准'
}

export const knowledgeStatusText = (value) =>
  ({ DRAFT: '草稿', PUBLISHED: '已发布', WITHDRAWN: '已撤回' })[value] || value || '未知'

export const ticketStatusText = (value) =>
  ({
    OPEN: '待接管',
    TAKEN_OVER: '处理中',
    CLOSED: '已结束',
  })[value] || value || '未知'

export const ticketReasonText = (value) =>
  ({
    knowledge_or_model_unresolved: '知识或模型未能解答',
    user_requested: '用户主动转人工',
    refund_review: '退款人工核对',
    payment_failure: '支付异常',
  })[value] || value || '未说明原因'

export const aclText = (value) =>
  ({
    PUBLIC: '所有访客',
    USER: '已登录用户',
    MERCHANT: '商家',
    ACTOR: '指定主体',
  })[value] || value || '未设置'

export const proposalStatusText = (value) =>
  ({
    CONFIRMED: '已确认 CONFIRMED',
    PENDING: '待确认',
    REJECTED: '已拒绝',
    EXPIRED: '已过期',
  })[value] || value || '未知'

export const requestKindText = (value) =>
  ({
    inquire_fact: '询问已发布事实',
    request_service: '要求未发布服务',
    request_exception: '要求例外裁决',
    request_handoff: '要求转交人工',
    clarify: '需要补充信息',
  })[value] || value || ''

export const evidenceKindText = (value) =>
  ({
    supported: '本轮有可见引用',
    none: '检索后合法空集',
    conflicting: '资料冲突',
    quarantined: '命中隔离资料',
    acl_denied: '当前身份不可见',
    unobserved: '本轮未检索',
  })[value] || value || ''

export const answerStatusText = (value) =>
  ({
    answered: '已答复',
    insufficient: '信息不足',
    conflicting: '资料冲突',
    needs_human: '转交人工',
  })[value] || value || ''

export const checkText = (value) =>
  ({
    compiled_decision_present: '已记录编译输入',
    policy_grounding_has_this_turn_citation: '政策结论带本轮引用',
    no_business_claim_has_no_citations: '寒暄未携带证据',
    proposal_is_not_execution: '提案未当作已成交',
    needs_human_has_ticket: '转人工已建工单',
    budget_within_limits: '未超出本轮预算',
    model_has_no_tools: '经营模型未调用工具',
    no_replan_on_same_watermark: '无新观测不重新规划',
    evidence_bound_or_waiting: '计划绑定证据或等待授权',
  })[value] || value || ''

export const checkStatusText = (value) =>
  ({ passed: '通过', failed: '未通过', not_applicable: '本轮不适用' })[value] || value || ''

export function skillBanner(decision) {
  if (!decision) return ''
  const skills = Object.entries(decision.skill_versions || {}).map(([name, version]) => `${name} ${version}`).join(' · ')
  return [decision.prompt_version, skills, modeText(decision.model_mode)].filter(Boolean).join(' · ')
}

export function json(value) {
  return JSON.stringify(value, null, 2)
}

export function text(value) {
  if (value === undefined || value === null) return '未知'
  if (typeof value === 'object') return json(value)
  return String(value)
}

export function badgeTone(status) {
  if (['COMPLETED', 'ACTIVE', 'APPROVED', 'PUBLISHED', 'TAKEN_OVER', 'CONFIRMED'].includes(status)) return 'ok'
  if (['WAIT_USER', 'WAIT_MERCHANT', 'WAIT_APPROVAL', 'WAIT_OUTCOME', 'WAIT_OBSERVATION', 'RUNNING', 'DRAFT', 'OPEN', 'EXECUTING'].includes(status)) return 'wait'
  if (['FAILED', 'REVOKED', 'WITHDRAWN', 'PAUSED', 'EXHAUSTED', 'PARTIALLY_APPLIED'].includes(status)) return 'warn'
  return ''
}

export function productLabel(id, products = []) {
  const hit = products.find((item) => item.product_id === id)
  return hit?.product_name || id || '未报告'
}

export function observationMetrics(summary) {
  if (!summary || typeof summary !== 'object') return []
  const rows = [
    ['impressions', '广告曝光'],
    ['clicks', '广告点击'],
    ['recommendation_impressions', '推荐曝光'],
    ['recommendation_clicks', '推荐点击'],
    ['paid_cents', '成交金额'],
    ['refunded_cents', '退款金额'],
  ]
  return rows
    .filter(([key]) => summary[key] !== undefined && summary[key] !== null)
    .map(([key, label]) => ({ key, label, value: summary[key], money: key.endsWith('_cents') }))
}
