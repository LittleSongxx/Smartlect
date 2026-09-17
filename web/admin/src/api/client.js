import { ref } from 'vue';

export const session = ref(null);
export const actionLabels = { activate_campaign: '启用活动', pause_campaign: '暂停活动', resume_campaign: '恢复活动', activate_creative: '启用素材', pause_creative: '暂停素材', resume_creative: '恢复素材', set_budget: '调整预算', replace_creative: '替换文案', set_recommendation_policy: '调整推荐策略' };
let epoch = 0;
export const ownerKey = value => value ? `${value.actor.subject_type}:${value.actor.actor_id}:${value.actor.execution_scope_id}:${value.actor.session_id}` : '';
export function clearSession() { epoch++; session.value = null; }
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export function errorText(reason) {
  const messages = { login_required: '请使用管理员账号登录。', invalid_session: '登录已失效，请重新登录。',
    permission_denied: '当前账号没有此操作权限。', version_conflict: '版本已变化，请刷新并重新核对。', ads_version_conflict: '活动或素材版本已变化，请刷新并重新核对。',
    csrf_denied: '会话校验已失效，请刷新。', origin_denied: '当前访问地址不在允许的管理地址内。',
    merchant_campaign_draft_required: '当前还没有活动草稿。请先到「活动与授权」创建 DRAFT 活动，再回来规划。',
    // growth 域的业务码：直接把机器码摆给管理员看不懂，这里给中文
    no_comments: '这件商品还没有评价，先有评价才能生成分析。',
    user_required: '请先登录后再操作。',
    conversation_not_found: '当前会话已失效，请刷新页面后重试。',
    conversation_version_conflict: '会话已在别处更新，请刷新后重试。',
    assistant_busy: '助手正在处理上一条消息，请稍候。',
    actor_run_limit: '同时进行的对话太多了，请等前面的完成再问。',
    proposal_not_found: '这张确认卡已不存在，请重新发起。',
    proposal_version_conflict: '确认卡已被更新，请刷新后重新核对。',
    proposal_not_confirmed: '这张确认卡还没被确认，无法执行。',
    action_already_terminal: '该动作已经结束，不能重复执行。',
    action_not_started: '该动作尚未开始，请稍后再试。',
    tool_call_not_found: '对应的执行记录已不存在，请刷新查看。',
    tool_call_already_terminal: '该执行已经结束，不能重复提交。',
    run_deadline_exceeded: '本次运行超时，请重新发起。',
    run_not_running: '本次运行已结束，请刷新查看结果。',
    human_control_active: '会话已转人工，自动回复暂停。',
    handoff_state_changed: '转人工状态已变化，请刷新会话。',
    evidence_not_found: '引用依据已失效，请重新提问。',
    citation_no_longer_visible: '引用的资料已不可见，请刷新后重试。',
    explicit_preference_has_priority: '这条偏好是您明确设定的，不会被自动改写。',
    invalid_preference_value: '偏好值不合法，请重新填写。',
    invalid_preference_key: '偏好项目不合法，请从列表中选择。',
    message_id_conflict: '消息编号冲突，请重新发送。',
    document_expired: '该资料已过期，不再用于回答。',
    knowledge_capacity_exceeded: '知识库已达容量上限，请先归档旧资料。',
    unsupported_document_format: '不支持的文件格式，请上传 PDF/Markdown/文本。',
    encrypted_pdf_not_supported: '带密码的 PDF 暂不支持，请先解密。',
    document_has_no_text: '文件里没有可提取的文字（可能是扫描件）。',
    document_input_too_large: '文件太大，请拆分后再上传。',
    document_text_too_large: '提取出的文字超出上限，请拆分后再上传。',
    document_invalid_text: '文件内容是乱码或非法编码，请检查编码后重试。',
    document_not_found: '资料不存在，可能已被删除。',
    document_not_draft: '该资料不是草稿状态，不能这样编辑。',
    pdf_page_limit: 'PDF 页数超出上限，请拆分后再上传。',
    pdf_content_limit: 'PDF 内容量超出上限，请拆分后再上传。',
    pdf_resource_limit: 'PDF 资源占用超出上限，请优化后再上传。',
    invalid_pdf: 'PDF 文件损坏或格式不合法。',
    invalid_document: '资料内容不合法，请检查后重试。',
    index_job_not_found: '索引任务不存在，请刷新列表。',
    index_job_not_running: '该索引任务已经结束。',
    index_job_not_resumable: '该索引任务不能续跑，请重新发起。',
    invalid_index_job_state: '索引任务状态已变化，请刷新。',
    incomplete_embeddings: '向量还没全部生成完，请稍后查看任务进度。',
    invalid_embeddings: '向量数据不合法，请重新生成。',
    duplicate_embedding_chunk: '存在重复切片，索引已跳过。',
    skill_not_editable: '该技能不可编辑，请新建版本。',
    skill_tools_not_authorized: '技能里的工具不在技能允许的白名单内。',
    invalid_skill_version: '技能版本不合法，请刷新后重试。',
    invalid_skill_structure: '技能结构不符合约定，请检查 JSON 结构。',
    invalid_skill_json: '技能 JSON 解析失败，请检查格式。',
    invalid_skill_instructions: '技能说明不合法，请检查后重试。',
    invalid_prompt_body: '提示词正文不合法，请检查后重试。',
    invalid_prompt_domain: '提示词域不合法，请从列表中选择。',
    invalid_prompt_kind: '提示词类型不合法，请从列表中选择。',
    prompt_version_not_found: '该提示词版本不存在，请刷新。',
    model_id_not_authorized: '该模型不在可服务的白名单里。',
    invalid_model_mode: '模型调用模式不合法。',
    ticket_not_found: '工单不存在，可能已被处理。',
    ticket_version_conflict: '工单已被其他人更新，请刷新后重试。',
    ticket_assigned_to_another: '该工单已由其他客服接管。',
    ticket_not_taken_over: '请先接管工单再回复。',
    invalid_ticket_action: '工单操作不合法，请刷新后重试。',
    invalid_ticket_evidence: '工单凭据不合法，请刷新后重试。',
    invalid_lease: '执行租约已失效，请重试。',
    lease_lost: '执行租约已丢失，本次操作未完成。',
    invalid_action_type: '动作类型不合法。',
    invalid_proposal: '提案内容不合法，请重新生成。',
    invalid_citations: '引用格式不合法，请重新提问。',
    invalid_evidence_ids: '引用凭据不合法。',
    invalid_approval: '批准信息不完整，请重新勾选。',
    invalid_expires_at: '有效期不合法，请重新选择。',
    invalid_validity_interval: '生效区间不合法，请检查起止时间。',
    facts_require_verbatim_evidence: '事实必须附原文依据，请从资料中选一段原文。',
    inference_requires_owned_evidence: '推断必须基于本方资料，请先关联资料。',
    unexpected_quote: '文本里出现了不符合约定的引号，请检查。',
    run_not_claimable: '该运行已被其他执行者领取。',
    run_version_conflict: '运行状态已变化，请刷新。',
    no_scored_comments: '这件商品的评价没有星级，无法统计星级分布。',
    invalid_insights_json: '模型返回的洞察不是合法 JSON，本次结果未保存。',
    invalid_insights_structure: '模型返回的洞察结构不符合约定，本次结果未保存。',
    invalid_suggestions_json: '模型返回的建议不是合法 JSON，本次结果未保存。',
    invalid_suggestions: '模型返回的建议结构不符合约定，本次结果未保存。' };
  const message = reason instanceof Error ? reason.message : '请求失败，请稍后重试。';
  // 未收录的原因码给出可读兜底，同时保留原因码便于排查
  return messages[message] || (/^[a-z][a-z0-9_]{3,}$/.test(message) ? `操作未完成（原因码：${message}）。` : message);
}
async function request(path, options = {}, java = false) {
  const started = epoch;
  const response = await fetch(`/admin-api${java ? '' : '/assistant'}${path}`, {
    credentials: 'same-origin', signal: AbortSignal.timeout(45000), ...options,
  });
  let result;
  try { result = await response.json(); } catch { throw new ApiError(response.status, '服务响应无法读取；请刷新查询原操作结果。'); }
  if (started !== epoch) throw new ApiError(409, '账号已变化，请重新查看当前账号数据。');
  if (!response.ok || (java && result.code !== 200)) {
    if (response.status === 401 || (java && result.code === 901)) clearSession();
    const detail = result.detail || result.error || result.info || '请求失败';
    throw new ApiError(response.status, typeof detail === 'string' ? detail : '请求参数不符合合同，请检查表单。');
  }
  if (java && ['/account/login', '/account/logout'].includes(path)) clearSession();
  return java ? result.data : result;
}
export const javaPost = (path, fields = {}) => request(path, { method: 'POST', body: new URLSearchParams(fields) }, true);
export const aiGet = path => request(path);
export async function loadSession() {
  const previous = ownerKey(session.value);
  const current = await aiGet('/session');
  if (current.actor?.subject_type !== 'merchant') { clearSession(); throw new ApiError(403, 'permission_denied'); }
  if (previous && previous !== ownerKey(current)) epoch++;
  session.value = current;
  return current;
}
export async function aiWrite(path, body, method = 'POST') {
  const previous = ownerKey(session.value);
  const current = await loadSession();
  if (previous && previous !== ownerKey(current)) throw new ApiError(409, '账号已变化，请重新查看后操作。');
  return request(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': current.csrf_token }, body: JSON.stringify(body) });
}
export async function selectScope(executionScopeId) {
  const current = await aiWrite('/scopes/select', { execution_scope_id: executionScopeId });
  if (current.actor?.subject_type !== 'merchant' || !current.csrf_token) throw new ApiError(403, 'permission_denied');
  epoch++; session.value = current;
  return current;
}
export function integer(value, label, min = 0) {
  const text = String(value).trim();
  if (!/^\d+$/.test(text) || !Number.isSafeInteger(Number(text)) || Number(text) < min || Number(text) > 1_000_000_000_000) throw new Error(`${label}必须是 ${min} 至 1000000000000 之间的整数。`);
  return Number(text);
}
export function money(cents) {
  return Number.isSafeInteger(cents) ? `${cents < 0 ? '-' : ''}${Math.floor(Math.abs(cents) / 100)}.${String(Math.abs(cents) % 100).padStart(2, '0')}` : '待核对';
}
export const timestamp = value => value ? new Date(value).toLocaleString('zh-CN', { timeZoneName: 'short' }) : '未记录';
