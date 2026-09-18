import { ref } from 'vue';

export interface Actor {
  actor_id: string; subject_type: 'user' | 'visitor'; session_id: string; execution_scope_id: string;
}
export interface Session { actor: Actor; csrf_token: string }
export interface Proposal {
  proposal_id: string; conversation_id: string; agent_run_id: string; action_type: 'order' | 'cancel' | 'refund';
  status: string; version: number; decision_version?: number; approved?: boolean;
  parameters: Record<string, any>; quote_total_cents?: number; quote_id?: string; expires_at: string;
  receipt?: Record<string, any>; updated_at?: string;
}
export interface Run {
  agent_run_id: string; conversation_id: string; message_id: string; parent_run_id?: string;
  state: string; model_mode: string; result?: Record<string, any>; created_at?: string;
}
export interface Message {
  message_id: string; agent_run_id: string | null; role: string; content: string; sequence: number;
}
export interface Conversation { conversation_id: string; messages?: Message[]; proposals?: Proposal[]; handoff?: Record<string, any> | null }
export interface RunEvent { agent_run_id: string; conversation_id: string; sequence: number; event_type: string; data: Record<string, any> }
export const session = ref<Session | null>(null);
let sessionRequest: Promise<Session> | undefined;
let sessionEpoch = 0;
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}
const descriptions: Record<string, string> = {
  login_required: '请先登录后再操作。', invalid_session: '登录已失效，请重新登录。',
  trial_read_only: '作品集试用账号只能浏览，不能下单、改密或改资料。',
  trial_chat_limit: '试用账号今日咨询次数已用完，请明天再试。',
  permission_denied: '当前账号没有此操作权限。', RECONFIRM_REQUIRED: '商品、金额或地址已变化，请重新生成提案并确认。',
  proposal_expired: '提案已过期，请重新生成。', conversation_busy: '当前会话正在处理，请稍后刷新查看。',
  commerce_outcome_unknown: '交易结果暂未核实，请刷新原操作查询结果。',
  recommendation_unavailable: '推荐暂时不可用，请稍后刷新。',
  ads_disabled: '广告投放已停用。',
  product_scope_denied: '该商品不在当前店铺可售范围内，请换一件再下单。',
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
};
export function errorText(error: unknown) {
  const raw = error instanceof Error ? error.message : '请求失败，请稍后重试。';
  // 未收录的原因码给出可读兜底，同时保留原因码便于排查
  return descriptions[raw] || (/^[a-z][a-z0-9_]{3,}$/.test(raw) ? `操作未完成（原因码：${raw}）。` : raw);
}
async function request<T>(url: string, options: RequestInit = {}, java = false): Promise<T> {
  const epoch = sessionEpoch;
  const response = await fetch(url, { ...options, credentials: 'same-origin' });
  const payload = await response.json();
  if (!response.ok || (java && payload.code !== 200)) {
    if (epoch === sessionEpoch && (response.status === 401 || (java && payload.code === 901))) {
      session.value = null;
      window.dispatchEvent(new Event('smartlect:identity-changed'));
    }
    throw new ApiError(response.status, payload.error || payload.detail || payload.info || '请求失败');
  }
  if (java && ['/api/account/login', '/api/account/logout'].includes(url)) {
    sessionEpoch++; sessionRequest = undefined;
  }
  return java ? payload.data : payload;
}
export const javaGet = <T = any>(path: string) => request<T>(`/api${path}`, {}, true);
export const javaPost = <T = any>(path: string, values: Record<string, string | number> = {}) =>
  request<T>(`/api${path}`, { method: 'POST', body: new URLSearchParams(Object.entries(values).map(([key, value]) => [key, String(value)])) }, true);
export const aiGet = <T = any>(path: string, signal?: AbortSignal) => request<T>(`/api/assistant${path}`, { signal });
export async function loadSession(signal?: AbortSignal): Promise<Session> {
  signal?.throwIfAborted();
  if (!sessionRequest) {
    const epoch = sessionEpoch; const previous = session.value;
    // Share only the in-flight read; every later write still refreshes identity and CSRF.
    const pending = (async () => {
      try {
        const current = await aiGet<Session>('/session');
        if (epoch === sessionEpoch) return session.value = current;
      } catch (error) { if (epoch === sessionEpoch) throw error; }
      return session.value && session.value !== previous ? session.value : loadSession();
    })().finally(() => { if (sessionRequest === pending) sessionRequest = undefined; });
    sessionRequest = pending;
  }
  if (!signal) return sessionRequest;
  // A short-lived exposure can stop waiting without cancelling another caller's bootstrap.
  return new Promise<Session>((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener('abort', abort, { once: true });
    sessionRequest!.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}
export async function refreshCsrf(signal?: AbortSignal): Promise<Session> {
  signal?.throwIfAborted();
  // Drop a completed/foreign in-flight read so this write gets its own nonce.
  // Concurrent readers started after this still join the new GET.
  sessionRequest = undefined;
  return loadSession(signal);
}

export async function aiWrite<T = any>(path: string, body: unknown, method = 'POST', signal?: AbortSignal) {
  const previous = session.value ? ownerKey(session.value.actor) : '';
  const current = await refreshCsrf(signal);
  if (previous && previous !== ownerKey(current.actor)) {
    window.dispatchEvent(new Event('smartlect:identity-changed'));
    throw new ApiError(409, '账号已切换，请在当前账号下重新查看并操作。');
  }
  return request<T>(`/api/assistant${path}`, {
    method, signal, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': current.csrf_token }, body: body === undefined ? undefined : JSON.stringify(body),
  });
}
export const aiPost = <T = any>(path: string, body: unknown, signal?: AbortSignal) => aiWrite<T>(path, body, 'POST', signal);
export function ownerKey(actor: Actor) {
  return `${actor.subject_type}:${actor.actor_id}:${actor.execution_scope_id}`;
}
