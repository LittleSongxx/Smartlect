import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import Account from '../src/views/Account.vue';
import AdsView from '../src/views/AdsView.vue';
import SupportView from '../src/views/SupportView.vue';
import KnowledgeView from '../src/views/KnowledgeView.vue';
import { aiWrite, clearSession, integer, loadSession, session } from '../src/api/client';
import { field, button } from './helpers';

const actor = { subject_type: 'merchant', actor_id: 'm1', session_id: 's1', execution_scope_id: 'store', permissions: ['admin:legacy'] };
const current = () => ({ actor: { ...actor }, csrf_token: 'current-csrf' });
const campaign = { campaign_id: 'c1', owner_id: 'm1', name: '真实商品广告', product_id: 'p1', sku_key: 'sku1', status: 'DRAFT', version: 3, budget_cents: 1000, spent_cents: 30, cpc_cents: 10 };
const grant = { grant_id: 'g1', initial_plan_id: 'stable-plan', initial_plan_version: 2, version: 1, envelope_hash: 'original-hash', approval_time: '2026-09-09T00:00:00Z', valid_until: '2030-01-01T00:00:00Z', envelope: {} };
let data; let calls; let handler; const wrappers = [];
const reply = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const render = async component => { const wrapper = mount(component); wrappers.push(wrapper); await flushPromises(); return wrapper; };
const form = (wrapper, heading) => wrapper.findAll('form').find(item => item.text().includes(heading));
beforeEach(() => {
  clearSession(); session.value = current(); calls = []; handler = null;
  data = { campaigns: [{ ...campaign }], creatives: [], grants: [{ ...grant }], account: { account_id: 'stable-account', spent_cents: 30, budget_cap_cents: 1000 }, actions: [], observations: [] };
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options }); const handled = await handler?.(path, options); if (handled) return handled;
    if (path === '/admin-api/assistant/session') return reply(current());
    if (path === '/admin-api/assistant/ads') return reply(structuredClone(data));
    if (path === '/admin-api/account/checkCode') return reply({ code: 200, data: { checkCodeKey: 'captcha-key', checkCode: 'data:image/png;base64,a' } });
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.unstubAllGlobals(); });

describe('Smartlect 管理端业务边界', () => {
  it('uses Java POST captcha and account/password form login with double-submit protection', async () => {
    clearSession(); let finish;
    handler = (path, options) => path === '/admin-api/account/login' ? new Promise(resolve => { finish = () => resolve(reply({ code: 200, data: null })); }) : null;
    const wrapper = await render(Account);
    expect(calls[0].options.method).toBe('POST');
    await field(wrapper, '账号').setValue('merchant'); await field(wrapper, '密码').setValue('secret'); await field(wrapper, '图片验证码').setValue('abcd');
    await wrapper.find('form').trigger('submit'); await wrapper.find('form').trigger('submit'); await flushPromises();
    const logins = calls.filter(item => item.path.endsWith('/account/login')); expect(logins).toHaveLength(1);
    expect(Object.fromEntries(logins[0].options.body)).toEqual({ account: 'merchant', password: 'secret', checkCode: 'abcd', checkCodeKey: 'captcha-key' });
    expect(logins[0].options.credentials).toBe('same-origin'); finish(); await flushPromises(); expect(session.value.actor.subject_type).toBe('merchant');
  });
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
  it('requires explicit grant approval and resets consent after any envelope edit', async () => {
    handler = path => path.endsWith('/ads/grants') ? reply({ grant_id: 'g-new' }) : null;
    const wrapper = await render(AdsView); const approval = form(wrapper, '明确批准稳定授权');
    await approval.trigger('submit'); await flushPromises(); expect(calls.some(item => item.path.endsWith('/ads/grants'))).toBe(false);
    await field(approval, '授权有效期').setValue('2030-01-01T12:00');
    await approval.find('input[type="checkbox"][value="p1"]').setValue(true);
    const consent = approval.find('.approval input'); await consent.setValue(true);
    await field(approval, '累计总上限').setValue('2000'); expect(consent.element.checked).toBe(false);
    await consent.setValue(true); await approval.trigger('submit'); await flushPromises();
    const request = calls.find(item => item.path.endsWith('/ads/grants')); const body = JSON.parse(request.options.body);
    expect(body.expected_campaign_versions).toEqual({ c1: 3 }); expect(body.expected_creative_versions).toEqual({}); expect(body).not.toHaveProperty('displayed_resources'); expect(body.envelope.product_scope).toEqual(['p1']); expect(body.envelope.budget_cap_cents).toBe(2000); expect(body.envelope.valid_until).toMatch(/Z$/); expect(body).not.toHaveProperty('approved');
  });
  it('sends DRAFT creation in integer cents without implicit activation or grant creation', async () => {
    handler = path => path.endsWith('/ads/campaigns') ? reply({ ...campaign }) : null;
    const wrapper = await render(AdsView); const draft = form(wrapper, '保存活动草稿');
    await field(draft, '活动名称').setValue('本地活动'); await field(draft, '真实商品').setValue('p1'); await field(draft, '真实 SKU').setValue('sku1');
    await draft.trigger('submit'); await flushPromises();
    const writes = calls.filter(item => item.options.method === 'POST'); expect(writes).toHaveLength(1);
    expect(JSON.parse(writes[0].options.body)).toMatchObject({ product_id: 'p1', sku_key: 'sku1', budget_cents: 1000, cpc_cents: 10 });
    expect(JSON.parse(writes[0].options.body)).not.toHaveProperty('status');
  });
  it('binds actions to the displayed grant and resource version; double click and refresh never replay writes', async () => {
    let finish;
    handler = path => path.endsWith('/ads/actions') ? new Promise(resolve => { finish = () => resolve(reply({ status: 'APPLIED' })); }) : null;
    const wrapper = await render(AdsView); await field(wrapper, '执行所用授权').setValue('g1'); await button(wrapper, '启用活动').trigger('click');
    const action = form(wrapper, '核对本次动作'); await action.trigger('submit'); await action.trigger('submit'); await flushPromises();
    const writes = calls.filter(item => item.path.endsWith('/ads/actions')); expect(writes).toHaveLength(1);
    const body = JSON.parse(writes[0].options.body); expect(body).toMatchObject({ grant_id: 'g1', plan_id: 'stable-plan', plan_version: 2, actions: [{ action_type: 'activate_campaign', campaign_id: 'c1', expected_version: 3 }] });
    expect(body.action_id).toBe(body.idempotency_key); finish(); await flushPromises(); await button(wrapper, '刷新事实').trigger('click'); await flushPromises();
    expect(calls.filter(item => item.path.endsWith('/ads/actions'))).toHaveLength(1);
  });
  it('reloads protective pause after rejection and retries only the original stable action payload', async () => {
    handler = path => { if (path.endsWith('/ads/actions')) { data.campaigns[0].status = 'PAUSED'; data.campaigns[0].pause_reason = 'stockout'; data.campaigns[0].version = 4; return reply({ detail: 'fresh_positive_stock_required' }, 409); } };
    const wrapper = await render(AdsView); await field(wrapper, '执行所用授权').setValue('g1'); await button(wrapper, '启用活动').trigger('click');
    await form(wrapper, '核对本次动作').trigger('submit'); await flushPromises(); expect(wrapper.text()).toContain('暂停原因：stockout'); expect(wrapper.text()).toContain('fresh_positive_stock_required');
    await form(wrapper, '核对本次动作').trigger('submit'); await flushPromises();
    const writes = calls.filter(item => item.path.endsWith('/ads/actions')); expect(writes).toHaveLength(2); expect(writes[1].options.body).toBe(writes[0].options.body);
    expect(JSON.parse(writes[1].options.body).actions[0].expected_version).toBe(3);
  });
  it('renders creative text as text and disables admin writes for a read-only session', async () => {
    data.creatives = [{ creative_id: 'cr1', campaign_id: 'c1', copy_text: '<img src=x onerror=alert(1)>', status: 'DRAFT', version: 1 }];
    handler = path => path.endsWith('/session') ? reply({ actor: { ...actor, permissions: ['analytics:read'] }, csrf_token: 'read' }) : null;
    const wrapper = await render(AdsView); expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>'); expect(wrapper.find('.creative img').exists()).toBe(false);
    expect(button(wrapper, '保存 DRAFT').element.closest('fieldset').disabled).toBe(true); expect(button(wrapper, '启用活动').element.disabled).toBe(true);
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
