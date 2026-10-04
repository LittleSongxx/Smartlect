import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { JSDOM } from 'jsdom';
import { createPinia, setActivePinia } from 'pinia';
import { watch } from 'vue';
import { session, type RunEvent } from '../src/api/client';
import { useAgentSession } from '../src/composables/useAgentSession';

const actor = { actor_id: 'user-1', subject_type: 'user' as const, session_id: 'session-1', execution_scope_id: 'store' };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const sse = (events: RunEvent[]) => new Response(
  events.map((event) => `id: ${event.sequence}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`).join(''),
  { headers: { 'Content-Type': 'text/event-stream' } });
const event = (sequence: number, event_type: string, data: Record<string, unknown>): RunEvent =>
  ({ agent_run_id: 'r1', conversation_id: 'c1', sequence, event_type, data });
const conversation = { conversation_id: 'c1', messages: [{ message_id: 'm1', agent_run_id: 'r1', role: 'user', content: '退货政策', sequence: 1 }] };

beforeEach(() => {
  setActivePinia(createPinia());
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  session.value = { actor, csrf_token: 'csrf-user-1' }; localStorage.clear(); useAgentSession().reset();
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('流式增量与可解释路由事件', () => {
  it('流式增量逐段拼接，replace 权威全文收口后不重复不残留', async () => {
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'live',
      result: { answer: '本店支持七天无理由退货。', answer_status: 'answered' } };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) return Promise.resolve(json(conversation));
      if (url.endsWith('/conversations')) return Promise.resolve(json([]));
      if (url.endsWith('/events')) return Promise.resolve(sse([
        event(1, 'message_delta', { text: '', replace: true }),               // 新一轮流式开始：重置游标
        event(2, 'message_delta', { text: '本店支持' }),                       // 流式增量
        event(3, 'message_delta', { text: '七天无理由' }),
        event(4, 'message_delta', { text: '本店支持七天无理由退货。', replace: true }), // 权威全文收口
        event(5, 'completed', { answer: '本店支持七天无理由退货。' }),
      ]));
      return Promise.resolve(json(run));
    });
    vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession();
    await chat.restore('c1');
    // 最终答案以 replace 全文为准，不与此前增量拼接重复（replace 协议的核心不变量）。
    expect(chat.runs.value.r1?.result?.answer).toBe('本店支持七天无理由退货。');
    expect(chat.runs.value.r1?.result?.answer?.match(/七天无理由/g)).toHaveLength(1);
  });

  it('decision 事件把子智能体派发翻译成用户可读进度', async () => {
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'live',
      result: { answer: 'done', answer_status: 'answered' } };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) return Promise.resolve(json(conversation));
      if (url.endsWith('/conversations')) return Promise.resolve(json([]));
      if (url.endsWith('/events')) return Promise.resolve(sse([
        event(1, 'decision', { fork: 'task_dispatch', reason: 'sub_agent_routing', task_count: 2,
          routing: [{ profile: 'retrieval-scout', status: 'succeeded' }, { profile: 'comparator', status: 'succeeded' }] }),
        event(2, 'decision', { fork: 'catalog_template_closeout', reason: 'catalog_facts_observed' }),
        event(3, 'completed', { answer: 'done' }),
      ]));
      return Promise.resolve(json(run));
    });
    vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession();
    const seen: string[] = [];
    // sync 刷新逐次捕获：默认 pre 刷新会把同一 tick 内的多次文案变化合并成最后一次。
    watch(chat.connection, (value) => seen.push(value), { flush: 'sync' });
    await chat.restore('c1');
    await flushPromises();
    // restore 收尾会把 connection 置为「已从服务器恢复」，这里断言的是事件消费期间
    // 的中间态：decision 事件按 fork 类型映射成用户可读进度文案。
    expect(seen).toContain('已并行派发 2 个检索子任务');
    expect(seen).toContain('已取得商品事实，正在整理推荐');
  });

  it('重放含增量的历史事件流，最终文本仍等于权威全文', async () => {
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'live',
      result: { answer: '退款需在签收后七天内发起。', answer_status: 'answered' } };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) return Promise.resolve(json(conversation));
      if (url.endsWith('/conversations')) return Promise.resolve(json([]));
      if (url.endsWith('/events')) return Promise.resolve(sse([
        event(1, 'message_delta', { text: '退款需在' }),
        event(2, 'message_delta', { text: '签收后七天内' }),
        event(3, 'message_delta', { text: '退款需在签收后七天内发起。', replace: true }),
        event(4, 'completed', { answer: '退款需在签收后七天内发起。' }),
      ]));
      return Promise.resolve(json(run));
    });
    vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession();
    await chat.restore('c1');
    expect(chat.runs.value.r1?.result?.answer).toBe('退款需在签收后七天内发起。');
  });
});
