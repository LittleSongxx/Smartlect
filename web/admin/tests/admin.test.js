import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import SupportView from '../src/views/SupportView.vue';
import KnowledgeView from '../src/views/KnowledgeView.vue';
import { aiWrite, clearSession, integer, loadSession, session } from '../src/api/client';
import ElementPlus from 'element-plus';
import { field, button, sharedComponents } from './helpers';

const actor = { subject_type: 'merchant', actor_id: 'm1', session_id: 's1', execution_scope_id: 'store', permissions: ['admin:legacy'] };
const current = () => ({ actor: { ...actor }, csrf_token: 'current-csrf' });
let calls; let handler; const wrappers = [];
const reply = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const render = async component => { const wrapper = mount(component, { global: { plugins: [ElementPlus], components: sharedComponents } }); wrappers.push(wrapper); await flushPromises(); return wrapper; };
const form = (wrapper, heading) => wrapper.findAll('form').find(item => item.text().includes(heading));
beforeEach(() => {
  clearSession(); session.value = current(); calls = []; handler = null;
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options }); const handled = await handler?.(path, options); if (handled) return handled;
    if (path === '/admin-api/assistant/session') return reply(current());
    if (path === '/admin-api/account/checkCode') return reply({ code: 200, data: { checkCodeKey: 'captcha-key', checkCode: 'data:image/png;base64,a' } });
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.unstubAllGlobals(); });

describe('Smartlect 管理端业务边界', () => {
  it('refreshes merchant CSRF on each write and blocks an account switch', async () => {
    handler = path => path.endsWith('/session') ? reply({ actor: { ...actor, actor_id: 'm2' }, csrf_token: 'new' }) : null;
    await expect(aiWrite('/ads/campaigns', { campaign_id: 'x' })).rejects.toThrow('账号已变化');
    expect(calls).toHaveLength(1);
    handler = path => path.endsWith('/session') ? reply({ actor: { ...actor, actor_id: 'm2' }, csrf_token: 'latest' }) : reply({ status: 'DRAFT' });
    await aiWrite('/ads/campaigns', { campaign_id: 'x' });
    expect(calls.at(-1).options.headers['X-CSRF-Token']).toBe('latest');
  });
  it('clears expired sessions and rejects non-merchant identities without posting', async () => {
    handler = () => reply({ detail: 'invalid_session' }, 401);
    await expect(aiWrite('/ads/actions', {})).rejects.toThrow('invalid_session'); expect(session.value).toBeNull(); expect(calls).toHaveLength(1);
    handler = () => reply({ actor: { ...actor, subject_type: 'user' }, csrf_token: 'bad' });
    await expect(loadSession()).rejects.toThrow('permission_denied'); expect(session.value).toBeNull();
  });
  it('preserves integer cents and rejects fractional, boolean, negative and imprecise values', () => {
    expect(integer('1005', '预算')).toBe(1005);
    for (const value of ['10.5', true, -1, '1e3', '', '9007199254740993']) expect(() => integer(value, '预算')).toThrow();
  });
  it('keeps human replies version-bound and does not replay after a conflict', async () => {
    const ticket = { ticket_id: 't1', conversation_id: 'co1', status: 'TAKEN_OVER', assigned_actor_id: 'm1', version: 5, reason: '人工核对' };
    handler = path => path.endsWith('/support') ? reply([ticket]) : path.endsWith('/support/t1') ? reply({ detail: 'ticket_version_conflict' }, 409) : null;
    const wrapper = await render(SupportView); await field(wrapper, '人工回复').setValue('已核对，稍后继续处理。'); await wrapper.find('form').trigger('submit'); await flushPromises();
    const write = calls.find(item => item.options.method === 'PATCH'); expect(JSON.parse(write.options.body)).toEqual({ action: 'reply', version: 5, reply: '已核对，稍后继续处理。' });
    expect(wrapper.text()).toContain('不会自动重发回复'); await button(wrapper, '刷新工单').trigger('click'); await flushPromises(); expect(calls.filter(item => item.options.method === 'PATCH')).toHaveLength(1);
  });
  it('requires a separate explicit operation before publishing a knowledge version', async () => {
    handler = path => path.endsWith('/knowledge') ? reply([{ doc_id: 'policy1', title: '退款政策', status: 'DRAFT', acl: 'PUBLIC', version: 2 }]) : path.endsWith('/publish') ? reply({ status: 'PUBLISHED' }) : path.endsWith('/knowledge/policy1/2') ? reply({ doc_id: 'policy1', title: '退款政策', version: 2, acl: 'PUBLIC', body: '此版本的可核对正文' }) : null;
    const wrapper = await render(KnowledgeView); await button(wrapper, '核对发布').trigger('click'); await flushPromises(); expect(calls.some(item => item.path.endsWith('/publish'))).toBe(false);
    await form(wrapper, '确认发布').trigger('submit'); await flushPromises(); expect(calls.filter(item => item.path.endsWith('/publish'))).toHaveLength(1); expect(calls.find(item => item.path.endsWith('/publish')).path).toBe('/admin-api/assistant/knowledge/policy1/2/publish');
  });
});
