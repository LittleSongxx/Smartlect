import { computed, ref } from 'vue';
import { acceptEvent, readSseFrame } from '@/utils/assistant';
import { aiGet, aiPost, ApiError, errorText, ownerKey, session, type Conversation, type Message, type Proposal, type Run, type RunEvent } from '@/api/client';

const conversationId = ref('');
const messages = ref<Message[]>([]);
const runs = ref<Record<string, Run>>({});
const history = ref<Conversation[]>([]);
const handoff = ref<Record<string, any> | null>(null);
const busy = ref(false);
const error = ref('');
const connection = ref('可以开始对话');
const pending = ref<{ message_id: string; text: string; product_id?: string; sku_key?: string; focus_mode?: string } | null>(null);
let generation = 0;
let stream: AbortController | null = null;
const cursors = new Map<string, number>();
const replayedDeltas = new Map<string, string>();
export const HANDOFF_SYNC_INTERVAL_MS = 10000;
const storageKey = () => session.value ? `smartlect:conversation:${ownerKey(session.value.actor)}` : '';
const visibleRuns = computed(() => Object.values(runs.value).filter((run) => !run.parent_run_id));

export function reset() {
  generation++; stream?.abort(); stream = null; cursors.clear(); replayedDeltas.clear();
  conversationId.value = ''; messages.value = []; runs.value = {}; history.value = []; handoff.value = null;
  error.value = ''; busy.value = false; pending.value = null; connection.value = '可以开始对话';
}
function updateProposal(proposal: Proposal) {
  for (const run of Object.values(runs.value)) {
    const previous = run.result?.proposal;
    if ((run.agent_run_id === proposal.agent_run_id || previous?.proposal_id === proposal.proposal_id)
        && (!previous || (previous.proposal_id === proposal.proposal_id && previous.version <= proposal.version))) {
      run.result = { ...run.result, proposal };
    }
  }
}
function applyEvent(event: RunEvent, runId: string) {
  if (!acceptEvent(event, runId, conversationId.value, cursors.get(runId) || 0)) return;
  cursors.set(runId, event.sequence);
  const run = runs.value[runId];
  if (!run) return;
  if (event.event_type === 'tool_started') connection.value = '正在查询商品、知识或订单事实';
  if (event.event_type === 'tool_result') connection.value = '查询已返回，正在整理回复';
  if (event.data?.proposal) {
    if (!run.result?.proposal) run.result = { ...run.result, proposal: event.data.proposal };
    updateProposal(event.data.proposal);
  }
  // Completed snapshots win over replayed deltas; reconnect cannot duplicate assistant text.
  if (event.event_type === 'message_delta' && ['CREATED', 'RUNNING'].includes(run.state)) {
    const piece = event.data.text || event.data.delta || '';
    const shown = run.result?.answer || '';
    const streamed = (replayedDeltas.get(runId) || '') + piece;
    replayedDeltas.set(runId, streamed);
    if (!shown || shown.startsWith(streamed) || streamed.startsWith(shown)) {
      run.result = { ...run.result, answer: streamed.length > shown.length ? streamed : shown };
    }
  }
  if (event.event_type === 'message_complete') {
    run.result = { ...run.result, answer: event.data.text || event.data.answer || run.result?.answer || '' };
  }
}
async function events(run: Run, epoch: number) {
  stream?.abort(); const controller = new AbortController(); stream = controller;
  const timeout = window.setTimeout(() => controller.abort(), 100000);
  try {
  const response = await fetch(`/api/assistant/runs/${run.agent_run_id}/events`, {
    credentials: 'same-origin', headers: { 'Last-Event-ID': String(cursors.get(run.agent_run_id) || 0) }, signal: controller.signal,
  });
  if (!response.ok || !response.body) throw new ApiError(response.status, '消息连接中断，可刷新恢复。');
  connection.value = '事件已连接';
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  try {
    while (epoch === generation) {
      const part = await reader.read();
      buffer = (buffer + decoder.decode(part.value, { stream: !part.done })).replace(/\r\n/g, '\n');
      let end = buffer.indexOf('\n\n');
      while (end !== -1) {
        const event = readSseFrame(buffer.slice(0, end));
        if (event) applyEvent(event, run.agent_run_id);
        buffer = buffer.slice(end + 2); end = buffer.indexOf('\n\n');
      }
      if (part.done) break;
    }
  } finally { reader.releaseLock(); }
  } finally { window.clearTimeout(timeout); }
}
async function watchRun(run: Run, epoch: number) {
  for (let attempt = 0; attempt < 3 && epoch === generation; attempt++) {
    try {
      await events(run, epoch);
    } catch (reason) {
      if (reason instanceof ApiError && [401, 403, 404].includes(reason.status)) throw reason;
      if (epoch === generation) connection.value = '连接中断，正在只读恢复';
    }
    if (epoch !== generation) return;
    try {
      const current = await aiGet<Run>(`/runs/${run.agent_run_id}`);
      if (epoch !== generation) return;
      if (['CREATED', 'RUNNING'].includes(current.state) && !current.result?.answer && runs.value[run.agent_run_id]?.result?.answer) {
        current.result = { ...current.result, answer: runs.value[run.agent_run_id]!.result!.answer };
      }
      const priorProposal = runs.value[run.agent_run_id]?.result?.proposal;
      const currentProposal = current.result?.proposal;
      if (priorProposal && (!currentProposal || (currentProposal.proposal_id === priorProposal.proposal_id && currentProposal.version < priorProposal.version))) {
        current.result = { ...current.result, proposal: priorProposal };
      }
      runs.value[run.agent_run_id] = current;
      if (!['CREATED', 'RUNNING'].includes(current.state)) return;
    } catch (reason) {
      if (reason instanceof ApiError && [401, 403, 404].includes(reason.status)) throw reason;
    }
    if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 1000 * (attempt + 1)));
  }
  if (epoch === generation) {
    connection.value = '未连接';
    throw new Error('连接恢复未完成，请点击刷新会话。原消息不会重新提交。');
  }
}
async function loadHistory() {
  const epoch = generation;
  try {
    const data = await aiGet<Conversation[] | { conversations: Conversation[] }>('/conversations');
    if (epoch === generation) history.value = Array.isArray(data) ? data : data.conversations;
  } catch (reason) {
    if (!(reason instanceof ApiError && reason.status === 404)) throw reason;
  }
}
async function restore(id = conversationId.value || localStorage.getItem(storageKey()) || '') {
  if (!id || !session.value) {
    if (session.value) connection.value = '可以开始对话';
    await loadHistory();
    return;
  }
  const epoch = generation;
  busy.value = true; error.value = '';
  try {
    const data = await aiGet<Conversation>(`/conversations/${encodeURIComponent(id)}`);
    const unique = [...new Set([...(data.messages || []).map((message) => message.agent_run_id),
      ...(data.proposals || []).map((proposal) => proposal.agent_run_id)].filter((id): id is string => Boolean(id)))];
    const saved = await Promise.all(unique.map((runId) => aiGet<Run>(`/runs/${runId}`)));
    const proposals = await Promise.all(saved.filter((run) => run.result?.proposal).map((run) => aiGet<Proposal>(`/proposals/${run.result!.proposal.proposal_id}`)));
    if (epoch !== generation) return;
    conversationId.value = data.conversation_id; messages.value = data.messages || [];
    handoff.value = data.handoff || null;
    runs.value = Object.fromEntries(saved.map((run) => [run.agent_run_id, run]));
    (data.proposals || []).forEach(updateProposal);
    proposals.forEach(updateProposal);
    localStorage.setItem(storageKey(), data.conversation_id);
    const last = saved.at(-1);
    if (last) {
      await watchRun(last, epoch);
      if (epoch !== generation) return;
      if (runs.value[last.agent_run_id]?.result?.proposal) {
        updateProposal(await aiGet<Proposal>(`/proposals/${runs.value[last.agent_run_id]!.result!.proposal.proposal_id}`));
      }
    }
    if (epoch === generation) { connection.value = '已从服务器恢复'; await loadHistory(); }
  } catch (reason) {
    if (epoch !== generation) return;
    error.value = errorText(reason); connection.value = '未连接';
    if (reason instanceof ApiError && [401, 403, 404].includes(reason.status)) {
      messages.value = []; runs.value = {}; conversationId.value = ''; localStorage.removeItem(storageKey());
    }
  } finally { if (epoch === generation) busy.value = false; }
}
async function newConversation() {
  if (busy.value) return;
  const epoch = generation;
  busy.value = true; error.value = '';
  try {
    const data = await aiPost<Conversation>('/conversations', {});
    if (epoch !== generation) return;
    stream?.abort(); cursors.clear(); replayedDeltas.clear(); conversationId.value = data.conversation_id;
    messages.value = []; runs.value = {}; pending.value = null; handoff.value = null;
    localStorage.setItem(storageKey(), data.conversation_id);
    connection.value = '可以开始对话';
    await loadHistory();
  } catch (reason) { if (epoch === generation) error.value = errorText(reason); }
  finally { if (epoch === generation) busy.value = false; }
}
async function send(text: string, retry = false, extra: { product_id?: string; sku_key?: string; focus_mode?: string } = {}) {
  if (busy.value || handoff.value || !text.trim()) return false;
  if (!conversationId.value) await newConversation();
  if (!conversationId.value) return false;
  const payload = retry && pending.value ? pending.value : {
    message_id: crypto.randomUUID(), text: text.trim(),
    ...(extra.focus_mode ? { focus_mode: extra.focus_mode } : {}),
    ...(extra.product_id ? { product_id: extra.product_id } : {}),
    ...(extra.sku_key ? { sku_key: extra.sku_key } : {}),
  };
  const epoch = generation; pending.value = payload; busy.value = true; error.value = '';
  if (!messages.value.some((message) => message.message_id === payload.message_id)) {
    messages.value.push({ message_id: payload.message_id, agent_run_id: '', role: 'user', content: payload.text, sequence: (messages.value.at(-1)?.sequence || 0) + 1 });
  }
  try {
    const run = await aiPost<Run>(`/conversations/${conversationId.value}/messages`, payload);
    if (epoch !== generation) return false;
    runs.value[run.agent_run_id] = run; pending.value = null;
    const displayed = messages.value.find((message) => message.message_id === payload.message_id);
    if (displayed) displayed.agent_run_id = run.agent_run_id;
    await watchRun(run, epoch);
    if (epoch !== generation) return false;
    await restore(); return true;
  } catch (reason) { if (epoch === generation) { error.value = errorText(reason); connection.value = '可刷新恢复'; } return false; }
  finally { if (epoch === generation) busy.value = false; }
}
async function propose(action_type: string, parameters: Record<string, any>) {
  if (busy.value || handoff.value) throw new Error('当前会话正在处理或已转人工，请稍后再试。');
  if (!conversationId.value) await newConversation();
  if (!conversationId.value) throw new Error(error.value || '无法创建会话');
  const epoch = generation; busy.value = true;
  try {
    const run = await aiPost<Run>(`/conversations/${conversationId.value}/proposals`, { message_id: crypto.randomUUID(), action_type, parameters });
    if (epoch !== generation) throw new Error('账号或会话已变化，请重新查看。');
    runs.value[run.agent_run_id] = run;
    await restore();
    return run;
  } finally { if (epoch === generation) busy.value = false; }
}
async function requestHandoff() {
  if (!conversationId.value || busy.value || handoff.value) return;
  const epoch = generation;
  busy.value = true; error.value = '';
  try { const ticket = await aiPost(`/conversations/${conversationId.value}/handoff`, {}); if (epoch === generation) handoff.value = ticket; }
  catch (reason) { if (epoch === generation) error.value = errorText(reason); }
  finally { if (epoch === generation) busy.value = false; }
}
function mergeMessages(incoming: Message[]) {
  const byId = new Map(messages.value.map((message) => [message.message_id, message]));
  for (const message of incoming) byId.set(message.message_id, message);
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
}
async function syncConversation() {
  const id = conversationId.value;
  if (!id || !session.value) return;
  const epoch = generation;
  try {
    const data = await aiGet<Conversation>(`/conversations/${encodeURIComponent(id)}`);
    if (epoch !== generation || conversationId.value !== id) return;
    messages.value = mergeMessages(data.messages || []);
    handoff.value = data.handoff || null;
    (data.proposals || []).forEach(updateProposal);
  } catch {
    
  }
}
export function useAgentSession() {
  return { conversationId, messages, runs, visibleRuns, history, handoff, busy, error, pending, connection,
    reset, restore, newConversation, send, propose, updateProposal, requestHandoff, syncConversation };
}
