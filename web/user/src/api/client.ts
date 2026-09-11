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
  permission_denied: '当前账号没有此操作权限。', RECONFIRM_REQUIRED: '商品、金额或地址已变化，请重新生成提案并确认。',
  proposal_expired: '提案已过期，请重新生成。', conversation_busy: '当前会话正在处理，请稍后刷新查看。',
  commerce_outcome_unknown: '交易结果暂未核实，请刷新原操作查询结果。',
  recommendation_unavailable: '推荐暂时不可用，请稍后刷新。',
  product_scope_denied: '该商品不在当前店铺可售范围内，请换一件再下单。',
};
export function errorText(error: unknown) {
  const raw = error instanceof Error ? error.message : '请求失败，请稍后重试。';
  return descriptions[raw] || raw;
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
export async function aiWrite<T = any>(path: string, body: unknown, method = 'POST', signal?: AbortSignal) {
  const previous = session.value ? ownerKey(session.value.actor) : '';
  await loadSession(signal);
  if (previous && previous !== ownerKey(session.value!.actor)) {
    window.dispatchEvent(new Event('smartlect:identity-changed'));
    throw new ApiError(409, '账号已切换，请在当前账号下重新查看并操作。');
  }
  return request<T>(`/api/assistant${path}`, {
    method, signal, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.value!.csrf_token }, body: body === undefined ? undefined : JSON.stringify(body),
  });
}
export const aiPost = <T = any>(path: string, body: unknown, signal?: AbortSignal) => aiWrite<T>(path, body, 'POST', signal);
export function ownerKey(actor: Actor) {
  return `${actor.subject_type}:${actor.actor_id}:${actor.execution_scope_id}`;
}
