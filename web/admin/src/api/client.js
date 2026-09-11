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
    merchant_campaign_draft_required: '当前还没有活动草稿。请先到「活动与授权」创建 DRAFT 活动，再回来规划。' };
  const message = reason instanceof Error ? reason.message : '请求失败，请稍后重试。';
  return messages[message] || message;
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
