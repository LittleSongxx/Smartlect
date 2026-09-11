import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { JSDOM } from 'jsdom';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import AgentConfirmCard from '../src/components/agent/AgentConfirmCard.vue';
import AgentChatItem from '../src/components/agent/AgentChatItem.vue';
import AgentChatList from '../src/views/agent/AgentChatList.vue';
import AgentWorkspace from '../src/views/agent/AgentWorkspace.vue';
import MarkdownContent from '../src/components/common/MarkdownContent.vue';
import { aiPost, session, type Proposal, type RunEvent } from '../src/api/client';
import { acceptEvent, decisionVersion, localDateTime, proposalExpired, proposalLabel, readSseFrame } from '../src/utils/assistant';
import { useAgentSession } from '../src/composables/useAgentSession';
import { addressLabel, productName, skuLabel } from '../src/utils/productDisplay';

const actor = { actor_id: 'user-1', subject_type: 'user' as const, session_id: 'session-1', execution_scope_id: 'store' };
const proposal: Proposal = { proposal_id: 'p1', conversation_id: 'c1', agent_run_id: 'r1', action_type: 'refund',
  status: 'PROPOSED', version: 1, parameters: { orderItemId: 'item1', refundAmountCents: 1200 }, expires_at: new Date(Date.now() + 600000).toISOString() };
const refundDisplay = { order: { orderId: 'order1', items: [{ orderId: 'order1', orderItemId: 'item1', productId: 'product1', productName: '已购旅行包', propertyInfo: '绿色，加大', buyCount: 1, paidAmount: 99, refundedAmount: 20 }] } };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
beforeEach(() => {
  setActivePinia(createPinia());
  // Node 25's ambient Web Storage is not the browser implementation used by this app.
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  session.value = { actor, csrf_token: 'csrf-user-1' }; localStorage.clear(); useAgentSession().reset();
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('交易确认边界', () => {
  it('退款按Java已购明细展示商品规格，忽略其他明细和查询金额', async () => {
    const fetch = vi.fn(() => Promise.resolve(json({ order: { ...refundDisplay.order, items: [...refundDisplay.order.items,
      { orderId: 'order1', orderItemId: 'other-item', productName: '不属于此退款的商品', propertyInfo: '标准', buyCount: 2 }] } })));
    vi.stubGlobal('fetch', fetch);
    const wrapper = mount(AgentConfirmCard, { props: { card: proposal }, global: { stubs: { RouterLink: true } } }); await flushPromises();
    expect(wrapper.get('.item-name').text()).toBe('已购旅行包'); expect(wrapper.get('.item-sku').text()).toBe('绿色，加大 × 1');
    expect(wrapper.text()).toContain('¥12.00'); expect(wrapper.text()).not.toContain('¥99'); expect(wrapper.text()).not.toContain('不属于此退款');
    expect(fetch.mock.calls).toHaveLength(1); expect((fetch.mock.calls as unknown as [string][])[0]?.[0]).toBe('/api/assistant/proposals/p1/display');
    expect(wrapper.get<HTMLButtonElement>('button.btn-confirm').element.disabled).toBe(false); wrapper.unmount();
  });
  it('PROPOSED到期后界面禁确认并引导新提案，已确认恢复不受原有效期阻挡', async () => {
    vi.useFakeTimers();
    let wrapper: ReturnType<typeof mount> | undefined;
    try {
      const start = Date.now(); const expires = new Date(start + 1000).toISOString();
      const fetch = vi.fn(() => Promise.resolve(json(refundDisplay))); vi.stubGlobal('fetch', fetch);
      wrapper = mount(AgentConfirmCard, { props: { card: { ...proposal, expires_at: expires } }, global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } });
      await vi.advanceTimersByTimeAsync(0);
      expect(localDateTime(expires)).not.toMatch(/\dT\d/); expect(localDateTime('bad-date')).toBe('有效期待核对');
      expect(wrapper.get<HTMLButtonElement>('button.btn-confirm').element.disabled).toBe(false);
      await vi.advanceTimersByTimeAsync(1100);
      expect(wrapper.text()).toContain('提案已过期'); expect(wrapper.text()).toContain('重新咨询并生成提案');
      expect(wrapper.get<HTMLButtonElement>('button.btn-confirm').element.disabled).toBe(true);
      await wrapper.get('button.btn-confirm').trigger('click'); expect(fetch.mock.calls).toHaveLength(1);
      expect(proposalExpired({ ...proposal, status: 'UNKNOWN', expires_at: expires }, start + 2000)).toBe(false);
    } finally { wrapper?.unmount(); vi.useRealTimers(); }
  });
  it('仅根据Java商品和规格ID展示名称，确认金额参数不受展示查询影响', async () => {
    const detail = { productInfo: { productId: 'product1', productName: '旅行收纳包' }, productPropertyList: [
      { propertyValues: [{ propertyValueId: 'size1', propertyValue: '标准' }, { propertyValueId: 'size2', propertyValue: '加大' }] },
      { propertyValues: [{ propertyValueId: 'color1', propertyValue: '绿色' }] },
    ] };
    expect(productName(detail, 'product1')).toBe('旅行收纳包'); expect(productName(detail, 'other-product')).toBe('商品名称待核对');
    expect(skuLabel(detail, 'size2-color1')).toBe('加大 / 绿色'); expect(skuLabel(detail, 'size2-unknown')).toBe('规格名称待核对');
    expect(skuLabel(undefined, 'size2')).toBe('规格名称待核对'); expect(addressLabel([], 'address1')).toBe('收货信息待核对');
    const original: Proposal = { ...proposal, action_type: 'order', quote_total_cents: 1234,
      parameters: { addressId: 'address1', orderList: [{ productId: 'product1', propertyValueIds: 'size2-color1', buyCount: 2 }] } };
    const fetch = vi.fn((url: string) => Promise.resolve(json({ code: 200, data: url.includes('getProduct') ? { ...detail, skuList: [{ price: 9999 }] } :
      [{ addressId: 'address1', addressee: '演示收件人', address: '演示路1号' }] })));
    vi.stubGlobal('fetch', fetch);
    const wrapper = mount(AgentConfirmCard, { props: { card: original }, global: { stubs: { RouterLink: true } } });
    await flushPromises();
    expect(wrapper.get('.item-name').text()).toBe('旅行收纳包'); expect(wrapper.get('.item-sku').text()).toBe('加大 / 绿色 × 2');
    expect(wrapper.text()).toContain('演示收件人 · 演示路1号'); expect(wrapper.text()).toContain('¥12.34'); expect(wrapper.text()).not.toContain('9999');
    expect(original.parameters.orderList[0]).toEqual({ productId: 'product1', propertyValueIds: 'size2-color1', buyCount: 2 });
    expect(fetch.mock.calls.every(([url]) => url.startsWith('/api/product/') || url.startsWith('/api/userAddress/'))).toBe(true);
    expect(wrapper.find('.proposal-evidence').exists()).toBe(false); wrapper.unmount();
  });
  it('展示查询失败不捏造名称，切换账号不接收旧地址异步结果', async () => {
    const original: Proposal = { ...proposal, action_type: 'order', quote_total_cents: 1234,
      parameters: { addressId: 'address1', orderList: [{ productId: 'product1', propertyValueIds: 'size1', buyCount: 1 }] } };
    const pendingReads: Array<(value: Response) => void> = [];
    const fetch = vi.fn(() => new Promise<Response>((resolve) => pendingReads.push(resolve))); vi.stubGlobal('fetch', fetch);
    const wrapper = mount(AgentConfirmCard, { props: { card: original }, global: { stubs: { RouterLink: true } } });
    session.value = { actor: { ...actor, actor_id: 'user-2' }, csrf_token: 'csrf-user-2' }; await flushPromises();
    pendingReads[0]!(json({ code: 200, data: [{ addressId: 'address1', addressee: '旧用户收件人', address: '旧用户地址' }] }));
    pendingReads[1]!(json({ code: 200, data: { productInfo: { productId: 'product1', productName: '旧名称' } } }));
    pendingReads[2]!(json({ error: 'service_unavailable' }, 503)); pendingReads[3]!(json({ error: 'service_unavailable' }, 503));
    await flushPromises();
    expect(wrapper.text()).not.toContain('旧用户'); expect(wrapper.text()).not.toContain('旧名称');
    expect(wrapper.get('.item-name').text()).toBe('商品名称待核对'); expect(wrapper.text()).toContain('收货信息待核对');
    expect(wrapper.get<HTMLButtonElement>('button.btn-confirm').element.disabled).toBe(true); wrapper.unmount();
  });
  it('受理不表示退款完成，订单创建不表示付款完成', () => {
    expect(proposalLabel({ ...proposal, status: 'UNKNOWN', receipt: { commandStatus: 'command_accepted', success: true } })).not.toContain('退款已完成');
    expect(proposalLabel({ ...proposal, status: 'SUCCEEDED', receipt: { commandStatus: 'business_pending' } })).toContain('待核实');
    expect(proposalLabel({ ...proposal, status: 'SUCCEEDED', receipt: { commandStatus: 'business_completed' } })).toBe('退款已完成');
    expect(proposalLabel({ ...proposal, action_type: 'order', status: 'SUCCEEDED', receipt: { commandStatus: 'business_completed' } })).toContain('付款请单独确认');
  });
  it('重试沿用用户曾批准的版本，且双击不会重发写请求', async () => {
    expect(decisionVersion({ ...proposal, version: 6, decision_version: 1 })).toBe(1);
    let finish: (value: Response) => void = () => {};
    const fetch = vi.fn((url: string) => url.endsWith('/session') ? Promise.resolve(json(session.value)) : new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal('fetch', fetch);
    const wrapper = mount(AgentConfirmCard, { props: { card: { ...proposal, status: 'UNKNOWN', version: 6, decision_version: 1 } }, global: { stubs: { RouterLink: true } } });
    const button = wrapper.get('button.btn-confirm'); await button.trigger('click'); await flushPromises(); await button.trigger('click');
    const writes = fetch.mock.calls.filter((call) => call[0].includes('/confirm'));
    expect(writes).toHaveLength(1);
    const options = (fetch.mock.calls as unknown as [string, RequestInit][]).find(([url]) => url.includes('/confirm'))![1];
    expect(JSON.parse(options.body as string)).toEqual({ proposal_version: 1, approved: true });
    expect(options.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-user-1' });
    finish(json({ proposal: { ...proposal, status: 'UNKNOWN', version: 7, decision_version: 1, receipt: { commandStatus: 'command_accepted' } } })); await flushPromises();
    expect(wrapper.emitted('updated')?.[0]?.[0]).toMatchObject({ status: 'UNKNOWN' });
    expect(wrapper.text()).not.toContain('退款已完成'); wrapper.unmount();
  });
  it('确认后变价显示重确认，保留原提案参数', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url.endsWith('/display')) return Promise.resolve(json(refundDisplay));
      if (url.endsWith('/session')) return Promise.resolve(json(session.value));
      if (options?.method === 'POST') return Promise.resolve(json({ error: 'RECONFIRM_REQUIRED' }, 409));
      return Promise.resolve(json({ ...proposal, status: 'FAILED', receipt: { error: 'RECONFIRM_REQUIRED' } }));
    }));
    const wrapper = mount(AgentConfirmCard, { props: { card: proposal }, global: { stubs: { RouterLink: true } } });
    await flushPromises();
    await wrapper.get('button.btn-confirm').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('重新生成提案并确认');
    expect(wrapper.emitted('updated')?.[0]?.[0]).toMatchObject({ status: 'FAILED', parameters: proposal.parameters }); wrapper.unmount();
  });
  it('账户变化后阻止旧页面写入新账户', async () => {
    const fetch = vi.fn(() => Promise.resolve(json({ actor: { ...actor, actor_id: 'user-2' }, csrf_token: 'csrf-user-2' })));
    vi.stubGlobal('fetch', fetch);
    await expect(aiPost('/preferences/purpose', { value: 'old user preference' })).rejects.toThrow('账号已切换');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('安全呈现与恢复', () => {
  it('检索和模型文本不执行HTML、链接、远程图片', () => {
    const wrapper = mount(MarkdownContent, { props: { content: '<script>alert(1)</script>\n[支付](javascript:alert(1)) ![tracking](https://example.invalid/pixel)' } });
    expect(wrapper.find('script').exists()).toBe(false); expect(wrapper.find('a').exists()).toBe(false); expect(wrapper.find('img').exists()).toBe(false);
    expect(wrapper.text()).toContain('<script>'); wrapper.unmount();
  });
  it('SSE以运行、会话、序号去重，不重放业务写操作', () => {
    const event = readSseFrame(': heartbeat\nevent: tool_result\nid: 2\ndata: {"agent_run_id":"r1",\ndata: "conversation_id":"c1","sequence":2,"event_type":"tool_result","data":{}}')!;
    expect(acceptEvent(event, 'r1', 'c1', 1)).toBe(true);
    expect(acceptEvent(event, 'r1', 'c1', 2)).toBe(false);
    expect(acceptEvent(event, 'r2', 'c1', 1)).toBe(false);
    expect(acceptEvent(event, 'r1', 'c2', 1)).toBe(false);
    expect(readSseFrame('data: not JSON')).toBeNull();
  });
  it('客服只展示文档名和正文标号，不打开规则原文或运行凭据', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] });
    const fetch = vi.fn(() => Promise.resolve(json({ title: '不应请求', body: '秘密原文' }))); vi.stubGlobal('fetch', fetch);
    const wrapper = mount(AgentChatItem, { props: { data: { agent_run_id: 'source-run', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'mock', result: {
      answer: '退货需按售后政策办理。', citations: [{ doc_id: 'policy', version: 2, chunk_id: 'policy:2:1', title: '售后政策', text: '当时发布的片段' }],
    } } }, global: { plugins: [router], stubs: { ElIcon: true } } });
    expect(wrapper.text()).toContain('售后政策');
    expect(wrapper.find('.cite-num').text()).toBe('1');
    expect(wrapper.text()).not.toContain('当时发布的片段');
    expect(wrapper.text()).not.toContain('policy:2:1');
    expect(wrapper.text()).not.toContain('查看来源');
    expect(wrapper.text()).not.toContain('运行凭据');
    expect(wrapper.find('.source-open').exists()).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('流断开后只读查询终态，不再次发送消息或批准', async () => {
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'RUNNING', model_mode: 'mock', result: null };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) return Promise.resolve(json({ conversation_id: 'c1', messages: [{ message_id: 'm1', agent_run_id: 'r1', role: 'user', content: '政策咨询', sequence: 1 }] }));
      if (url.endsWith('/conversations')) return Promise.resolve(json([]));
      if (url.endsWith('/events')) return Promise.reject(new Error('network interrupted'));
      const calls = fetch.mock.calls.filter((call) => call[0].endsWith('/runs/r1')).length;
      return Promise.resolve(json(calls > 1 ? { ...run, state: 'COMPLETED', result: { answer: '已完成的政策回答' } } : run));
    }); vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession(); await chat.restore('c1');
    expect(chat.runs.value.r1?.state).toBe('COMPLETED'); expect(chat.error.value).toBe('');
    expect(fetch.mock.calls.filter((call) => call[0].includes('/messages') || call[0].includes('/confirm'))).toHaveLength(0);
  });
  it('提案已提交但run结果丢失时恢复原卡片，人工接管禁用确认且全程不POST', async () => {
    const persisted = { ...proposal, version: 3 };
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'FAILED', model_mode: 'mock', result: null };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) return Promise.resolve(json({ conversation_id: 'c1', messages: [], proposals: [persisted], handoff: { ticket_id: 't1', status: 'TAKEN_OVER' } }));
      if (url.endsWith('/conversations')) return Promise.resolve(json([]));
      if (url.endsWith('/events')) return Promise.resolve(new Response(''));
      if (url.endsWith('/proposals/p1')) return Promise.resolve(json(persisted));
      return Promise.resolve(json(run));
    }); vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession(); await chat.restore('c1');
    expect(chat.error.value).toBe(''); expect(chat.runs.value.r1?.state).toBe('FAILED');
    expect(chat.runs.value.r1?.result?.proposal).toEqual(persisted);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] });
    const wrapper = mount(AgentChatList, { global: { plugins: [router], stubs: { ElIcon: true } } });
    expect(wrapper.text()).toContain('等待您的确认');
    expect(wrapper.get<HTMLButtonElement>('button.btn-confirm').element.disabled).toBe(true);
    await wrapper.get('button.btn-confirm').trigger('click'); await flushPromises();
    chat.updateProposal({ ...persisted, version: 2, status: 'EXPIRED' });
    expect(chat.runs.value.r1?.result?.proposal.status).toBe('PROPOSED');
    chat.updateProposal({ ...persisted, version: 4, status: 'EXPIRED' }); await flushPromises();
    expect(wrapper.text()).toContain('提案已过期'); expect(wrapper.find('button.btn-confirm').exists()).toBe(false);
    for (const [, options] of fetch.mock.calls as unknown as [string, RequestInit?][]) expect(options?.method).not.toBe('POST');
    wrapper.unmount();
  });
  it('刷新只发GET，加载持久化原提案的新状态，SSE回放不重复回复', async () => {
    const current = { ...proposal, status: 'SUCCEEDED', decision_version: 1, version: 5, receipt: { commandStatus: 'business_completed' } };
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'mock', result: { answer: '原始回复', proposal } };
    const event: RunEvent = { agent_run_id: 'r1', conversation_id: 'c1', sequence: 1, event_type: 'message_delta', data: { text: '原始回复' } };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) return Promise.resolve(json({ conversation_id: 'c1', handoff: { ticket_id: 'ticket1', status: 'TAKEN_OVER' }, messages: [
        { message_id: 'm1', agent_run_id: 'r1', role: 'user', content: '退款', sequence: 1 },
        { message_id: 'human-1', agent_run_id: null, role: 'assistant', content: '人工已核实', sequence: 2 },
      ] }));
      if (url.endsWith('/conversations')) return Promise.resolve(json([{ conversation_id: 'c1' }]));
      if (url.endsWith('/proposals/p1')) return Promise.resolve(json(current));
      if (url.endsWith('/events')) return Promise.resolve(new Response(`data: ${JSON.stringify(event)}\n\n`));
      return Promise.resolve(json(run));
    }); vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession(); await chat.restore('c1');
    expect(chat.error.value).toBe(''); expect(chat.runs.value.r1?.result?.answer).toBe('原始回复');
    expect(chat.runs.value.r1?.result?.proposal.status).toBe('SUCCEEDED');
    chat.updateProposal(proposal);
    expect(chat.runs.value.r1?.result?.proposal.version).toBe(5);
    expect(chat.handoff.value?.status).toBe('TAKEN_OVER'); expect(chat.messages.value.at(-1)?.content).toBe('人工已核实');
    expect(fetch.mock.calls.some((call) => call[0].includes('/runs/null'))).toBe(false);
    for (const [, options] of fetch.mock.calls as unknown as [string, RequestInit?][]) expect(options?.method).not.toBe('POST');
    expect(localStorage.getItem('smartlect:conversation:user:user-1:store')).toBe('c1');
  });
  it('转人工后安静同步只GET，合并人工回复且不POST、不置busy', async () => {
    let includeHuman = false;
    const run = { agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'mock', result: { answer: '已转交' } };
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/conversations/c1')) {
        return Promise.resolve(json({
          conversation_id: 'c1',
          handoff: { ticket_id: 'ticket1', status: 'TAKEN_OVER' },
          messages: [
            { message_id: 'm1', agent_run_id: 'r1', role: 'user', content: '退款', sequence: 1 },
            ...(includeHuman ? [{ message_id: 'human-2', agent_run_id: null, role: 'assistant', content: '客服已回复', sequence: 2 }] : []),
          ],
        }));
      }
      if (url.endsWith('/conversations')) return Promise.resolve(json([{ conversation_id: 'c1' }]));
      if (url.endsWith('/events')) return Promise.resolve(new Response(''));
      return Promise.resolve(json(run));
    });
    vi.stubGlobal('fetch', fetch);
    const chat = useAgentSession();
    await chat.restore('c1');
    expect(chat.messages.value).toHaveLength(1);
    includeHuman = true;
    await chat.syncConversation();
    expect(chat.busy.value).toBe(false);
    expect(chat.messages.value.at(-1)?.content).toBe('客服已回复');
    expect(chat.handoff.value?.status).toBe('TAKEN_OVER');
    for (const [, options] of fetch.mock.calls as unknown as [string, RequestInit?][]) expect(options?.method).not.toBe('POST');
  });
  it('路由 conversation 查询参数会恢复该会话', async () => {
    const fetch = vi.fn((url: string) => {
      if (url.includes('/conversations/playbook-c')) return Promise.resolve(json({
        conversation_id: 'playbook-c', messages: [{ message_id: 'human-1', agent_run_id: null, role: 'assistant', content: '人工已核实', sequence: 1 }],
        handoff: { ticket_id: 'ticket1', status: 'TAKEN_OVER' },
      }));
      if (url.endsWith('/conversations')) return Promise.resolve(json([{ conversation_id: 'playbook-c' }]));
      return Promise.resolve(json({ actor, csrf_token: 'csrf-user-1' }));
    });
    vi.stubGlobal('fetch', fetch);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/assistant', component: AgentWorkspace }] });
    await router.push('/assistant?conversation=playbook-c');
    await router.isReady();
    const wrapper = mount(AgentWorkspace, { global: { plugins: [router], stubs: { AgentChatList: true, AgentSendPanel: true } } });
    await flushPromises();
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/conversations/playbook-c'))).toBe(true);
    expect(localStorage.getItem('smartlect:conversation:user:user-1:store')).toBe('playbook-c');
    wrapper.unmount();
  });
  it('shows a compiled decision snapshot without changing the visible answer', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] });
    const wrapper = mount(AgentChatItem, {
      props: {
        data: {
          agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state: 'COMPLETED', model_mode: 'live',
          result: {
            answer: '本店支持七天无理由。', answer_status: 'answered',
            decision: {
              plane: 'shopping', request_kind: 'inquire_fact', evidence_kind: 'supported',
              compiled_answer_status: 'answered', accepted_tools: ['search_knowledge'],
              prompt_version: 'shopping-react-v23', skill_versions: { support_policy: '1.5.0' }, model_mode: 'live',
              budget: { model_attempts_used: 2, model_attempts_limit: 6, tool_calls_used: 1, tool_calls_limit: 10, retrieval_calls_used: 1, retrieval_calls_limit: 2 },
            },
            checks: [{ id: 'compiled_decision_present', status: 'passed' }],
          },
        },
      },
      global: { plugins: [router], stubs: { ElIcon: true } },
    });
    expect(wrapper.text()).toContain('本店支持七天无理由');
    expect(wrapper.text()).toContain('本轮如何决定');
    expect(wrapper.text()).toContain('询问已发布事实');
    expect(wrapper.text()).toContain('已记录编译输入');
    wrapper.unmount();
  });
});
