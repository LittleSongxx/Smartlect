import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import SupportView from '../src/views/SupportView.vue';
import { clearSession, session } from '../src/api/client';

const actor = { subject_type: 'merchant', actor_id: 'support-admin', session_id: 'session', execution_scope_id: 'scope', permissions: ['admin:legacy'] };
const ticket = { ticket_id: 'ticket', conversation_id: 'conversation', status: 'TAKEN_OVER', assigned_actor_id: actor.actor_id, version: 2, reason: '退款人工核对' };
const message = (sequence, content) => ({ message_id: 'm' + sequence, sequence, role: 'user', content, created_at: '2026-09-09T10:00:00Z', agent_run_id: 'run' });
let wrapper, requests, handle;
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => structuredClone(body) });
const button = text => wrapper.findAll('button').find(item => item.text() === text);
const page = () => ({ ticket, conversation: { actor_id: 'customer', subject_type: 'user' }, messages: [message(2, '请人工核对原退款')],
  runs: [{ agent_run_id: 'run', state: 'CANCELLED', model_mode: 'rule-fallback', result: { answer_status: 'needs_human', citations: [{
    doc_id: 'policy', version: 3, chunk_id: 'chunk', title: '原退款规则', source_uri: 'javascript:alert(1)', content: '<img src=x onerror=alert(1)>', start_line: 2, end_line: 4,
  }] } }], proposals: [{ proposal_id: 'original-proposal', status: 'CONFIRMED', action_type: 'refund', version: 4,
    approved: true, outcome: 'unknown', parameters: { orderId: 'original-order', refundAmountCents: 500 }, receipt: { status: 'UNKNOWN' } }], next_before_sequence: 2 });

beforeEach(() => {
  clearSession(); session.value = { actor, csrf_token: 'csrf' }; requests = []; handle = null;
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    requests.push({ path, options }); const result = handle?.(path, options); if (result) return result;
    if (path.endsWith('/session')) return response({ actor, csrf_token: 'csrf' });
    if (path.endsWith('/support')) return response([ticket]);
    if (path.endsWith('/support/ticket')) return response(page());
    if (path.endsWith('?before_sequence=2')) return response({ ...page(), messages: [message(1, '最初的退款问题')], next_before_sequence: null });
    throw new Error('Unexpected request: ' + path);
  }));
});
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); });

describe('人工工单持久会话详情', () => {
  it('loads and merges real API pages, showing escaped historical citations and current proposals without trade controls', async () => {
    wrapper = mount(SupportView); await flushPromises();
    expect(requests.some(item => item.path.endsWith('/support/ticket'))).toBe(false);
    await button('查看会话').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('请人工核对原退款');
    expect(wrapper.text()).toContain('原退款规则'); expect(wrapper.text()).toContain('CONFIRMED');
    expect(wrapper.text()).toContain('unknown'); expect(wrapper.text()).toContain('original-order');
    expect(wrapper.find('.support-detail img').exists()).toBe(false);
    expect(wrapper.find('.support-detail a[href^="javascript:"]').exists()).toBe(false);
    await button('加载更早消息').trigger('click'); await flushPromises();
    expect(wrapper.findAll('.support-message').map(item => item.text())).toEqual([
      expect.stringContaining('最初的退款问题'), expect.stringContaining('请人工核对原退款'),
    ]);
    expect(wrapper.text().match(/original-proposal/g)).toHaveLength(1);
    expect(button('加载更早消息')).toBeUndefined();
    expect(wrapper.findAll('.support-detail button').map(item => item.text())).toEqual(['收起会话']);
    expect(requests.every(item => !item.options.method)).toBe(true);
  });

  it('shows a read-only compiled decision snapshot on the linked run', async () => {
    handle = path => path.endsWith('/support/ticket') ? response({
      ...page(),
      runs: [{
        ...page().runs[0],
        result: {
          ...page().runs[0].result,
          decision: { request_kind: 'inquire_fact', evidence_kind: 'supported', compiled_answer_status: 'needs_human' },
          checks: [{ id: 'needs_human_has_ticket', status: 'passed' }],
        },
      }],
    }) : null;
    wrapper = mount(SupportView); await flushPromises();
    await button('查看会话').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('本轮如何决定');
    expect(wrapper.text()).toContain('询问已发布事实');
    expect(wrapper.text()).toContain('转人工已建工单');
    expect(wrapper.find('.support-detail .decision-card').exists()).toBe(true);
  });

  it('clears displayed context when an older-page request is denied after another assignment', async () => {
    wrapper = mount(SupportView); await flushPromises(); await button('查看会话').trigger('click'); await flushPromises();
    handle = path => path.includes('before_sequence') ? response({ error: 'ticket_assigned_to_another' }, 403) : null;
    await button('加载更早消息').trigger('click'); await flushPromises();
    expect(wrapper.find('.support-detail').exists()).toBe(false);
    expect(wrapper.text()).toContain('ticket_assigned_to_another');
    expect(requests.every(item => !item.options.method)).toBe(true);
  });

  it('disables another operator’s context and keeps detail reads separate from explicit takeover', async () => {
    handle = path => path.endsWith('/support') ? response([{ ...ticket, assigned_actor_id: 'another-admin' }]) : null;
    wrapper = mount(SupportView); await flushPromises();
    expect(button('查看会话').element.disabled).toBe(true);
    expect(requests.some(item => item.path.endsWith('/support/ticket'))).toBe(false);
  });
});
