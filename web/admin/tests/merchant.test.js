import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import MerchantView from '../src/views/MerchantView.vue';
import AdsView from '../src/views/AdsView.vue';
import App from '../src/GrowthShell.vue';
import { createAdminRouter } from '../src/router.js';
import { aiGet, aiWrite, clearSession, selectScope, session } from '../src/api/client';

const actor = { subject_type: 'merchant', actor_id: 'm1', session_id: 's1', execution_scope_id: 'store', permissions: ['admin:legacy'] };
const plan = { plan_id: 'plan1', version: 3, status: 'WAIT_APPROVAL', observation_id: 'obs1', grant_id: null, diagnosis: [{ code: 'payment_failures', explanation: 'Java 记录了一次模拟渠道拒付；其他原因仍需新证据。', evidence_ids: ['ev1'], observed_facts: [{ evidence_id: 'ev1', metric: 'declined_attempts', value: 1 }] }], spec: { objective: '核对净成交并保护库存', summary: '先保护已观察售罄的活动。', product_scope: ['p1'], period: 'scope_lifetime', planned_budget_cents: 100, evidence_ids: ['ev1'], actions: [{ action_type: 'pause_campaign', campaign_id: 'c1', expected_version: 4 }], expected_signals: ['等待新的库存和支付尝试事实'] } };
const campaign = { campaign_id: 'c1', name: '活动', owner_id: 'm1', product_id: 'p1', sku_key: 'hash1', status: 'ACTIVE', version: 4, budget_cents: 100, spent_cents: 20, cpc_cents: 10 };
const sku = { product_id: 'p1', sku_key: 'hash1', product_name: '真实产品', sku_name: '黑色 256G', price_cents: 1999, stock: 3 };
const response = (value, status=200) => ({ ok: status < 400, status, json: async () => value });
let state, ads, calls, handler, currentActor; const wrappers=[];
const button = (wrapper,name) => wrapper.findAll('button').find(item => item.text() === name);
const field = (wrapper,name) => wrapper.findAll('label').find(item => item.text().startsWith(name)).find('input,textarea,select');
const render = async (component,options={}) => {
  const global = { ...(options.global || {}) };
  if (component === App) {
    const router = createAdminRouter(createMemoryHistory());
    await router.push('/merchant');
    global.plugins = [...(global.plugins || []), router];
    const wrapper = mount(component, { ...options, global });
    wrappers.push(wrapper);
    await router.isReady();
    await flushPromises();
    return wrapper;
  }
  const wrapper = mount(component, options);
  wrappers.push(wrapper);
  await flushPromises();
  return wrapper;
};
beforeEach(() => {
  clearSession(); currentActor={...actor}; session.value={actor:currentActor,csrf_token:'scope-store'}; calls=[]; handler=null;
  state={observations:[],plans:[structuredClone(plan)],runs:[],memories:[],account:{spent_cents:20,budget_cap_cents:100},grant:null};
  ads={campaigns:[{...campaign}],creatives:[],grants:[],actions:[],observations:[],account:null};
  vi.stubGlobal('fetch',vi.fn(async(path,options={})=>{
    calls.push({path,options}); const handled=await handler?.(path,options); if(handled)return handled;
    if(path.endsWith('/session'))return response({actor:currentActor,csrf_token:`scope-${currentActor.execution_scope_id}`});
    if(path==='/admin-api/assistant/merchant')return response(structuredClone(state));
    if(path==='/admin-api/assistant/ads')return response(structuredClone(ads));
    if(path.endsWith('/ads/catalog'))return response({items:[sku],observed_at:'2026-09-09T00:00:00Z'});
    if(path.endsWith('/scopes'))return response({items:[{execution_scope_id:'store',label:'店铺'},{execution_scope_id:'demo-1',label:'独立演示'}]});
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(()=>{wrappers.splice(0).forEach(wrapper=>wrapper.unmount());vi.useRealTimers();vi.unstubAllGlobals();});

it('shows actual model mode, preserves unknown usage and renders authority-backed diagnoses as text',async()=>{
  state.runs=[{agent_run_id:'r1',state:'WAIT_USER',model_mode:'live',context:{model_mode:'rule-fallback',model_calls:1,model_attempts:[{usage:{input_tokens:12,output_tokens:null},cost_estimate_cny:null}]},result:{decision:{plane:'merchant',prompt_version:'merchant-plan-v19',skill_versions:{campaign_plan:'1.11.0'},model_mode:'rule-fallback',wait_reason:'WAIT_MERCHANT',budget:{model_attempts_used:1,model_attempts_limit:4}},checks:[{id:'model_has_no_tools',status:'passed'}]}}];
  state.plans[0].spec.summary='<img src=x onerror=alert(1)>';
  const wrapper=await render(MerchantView);
  expect(wrapper.text()).toContain('规则降级 rule-fallback');expect(wrapper.text()).toContain('输入 Token 12');expect(wrapper.text()).toContain('输出 Token 未知');expect(wrapper.text()).toContain('费用估算 ¥未知');
  expect(wrapper.text()).toContain('权威支付尝试失败');expect(wrapper.text()).toContain('Java 记录了一次模拟渠道拒付');expect(wrapper.text()).toContain('本轮如何决定');expect(wrapper.text()).toContain('经营模型未调用工具');expect(wrapper.find('img').exists()).toBe(false);
});

it('preserves the original run request after a network failure and never starts a new run for unchanged observation',async()=>{
  let writes=0;
  handler=(path)=>{if(path.endsWith('/merchant/runs')){if(writes++===0)throw new TypeError('Network unavailable');return response({state:'WAIT_OUTCOME',unchanged_observation:true,latest_plan:plan});}};
  const wrapper=await render(MerchantView);const form=wrapper.find('form');
  await field(wrapper,'规划方式').setValue('rule');await field(wrapper,'计划预算约束').setValue('100');await wrapper.find('input[type=checkbox][value=p1]').setValue(true);
  await form.trigger('submit');await flushPromises();expect(field(wrapper,'目标和约束').element.readOnly).toBe(true);
  await form.trigger('submit');await flushPromises();const requests=calls.filter(item=>item.path.endsWith('/merchant/runs'));
  expect(requests).toHaveLength(2);expect(requests[0].options.body).toBe(requests[1].options.body);expect(JSON.parse(requests[0].options.body)).toMatchObject({mode:'rule',planned_budget_cents:100,product_scope:['p1']});
  expect(wrapper.text()).toContain('本次未启动模型');expect(calls.some(item=>/\/merchant\/runs\//.test(item.path))).toBe(false);
});

it('polls an existing run only with GET and stops after persisted terminal state',async()=>{
  vi.useFakeTimers({toFake:['setTimeout','clearTimeout','Date']});
  state.runs=[{agent_run_id:'r1',state:'RUNNING',model_mode:'live',context:{}}];
  handler=path=>{if(path.endsWith('/merchant/runs/r1')){state.runs[0].state='WAIT_OUTCOME';return response({...state.runs[0]});}};
  const wrapper=await render(MerchantView);await vi.advanceTimersByTimeAsync(2000);await flushPromises();await vi.advanceTimersByTimeAsync(10000);await flushPromises();
  expect(calls.filter(item=>item.path.endsWith('/merchant/runs/r1'))).toHaveLength(1);expect(calls.some(item=>item.options.method==='POST')).toBe(false);expect(wrapper.text()).toContain('等待新结果');
});

it('never auto-approves a plan and sends the displayed version to deterministic execution',async()=>{
  handler=path=>path.endsWith('/plans/plan1/execute')?response({...plan,status:'WAIT_APPROVAL'}):null;
  const wrapper=await render(MerchantView);
  await button(wrapper,'查看计划并明确批准授权').trigger('click');expect(wrapper.emitted('review-grant')[0][0]).toMatchObject({plan_id:'plan1',version:3});expect(calls.some(item=>item.options.method==='POST')).toBe(false);
  await button(wrapper,'核对授权并执行 / 恢复回执').trigger('click');await flushPromises();const write=calls.find(item=>item.path.endsWith('/plans/plan1/execute'));
  expect(JSON.parse(write.options.body)).toEqual({expected_version:3});expect(write.options.headers['X-CSRF-Token']).toBe('scope-store');
});

it('binds merchant grant approval to the immutable plan and currently displayed resource maps',async()=>{
  handler=path=>path.endsWith('/ads/grants')?response({grant_id:'g1'}):null;
  const wrapper=await render(AdsView,{props:{merchantPlan:plan}});
  expect(field(wrapper,'首次计划 ID').element.value).toBe('plan1');expect(field(wrapper,'首次计划 ID').element.readOnly).toBe(true);expect(field(wrapper,'首次计划版本').element.value).toBe('3');
  await field(wrapper,'授权有效期').setValue('2030-01-01T12:00');await wrapper.find('.approval input').setValue(true);
  await wrapper.findAll('form').find(item=>item.text().includes('明确批准稳定授权')).trigger('submit');await flushPromises();
  const body=JSON.parse(calls.find(item=>item.path.endsWith('/ads/grants')).options.body);
  expect(body).toMatchObject({merchant_plan_id:'plan1',initial_plan_id:'plan1',initial_plan_version:3,expected_campaign_versions:{c1:4},expected_creative_versions:{},envelope:{objective:plan.spec.objective,product_scope:['p1']}});expect(wrapper.emitted('grant-approved')).toHaveLength(1);
  expect(calls.some(item=>item.path.endsWith('/plans/plan1/execute'))).toBe(false);
});

it('approves the reviewed text only after renewed consent when the original experience is edited',async()=>{
  state.memories=[{memory_id:'m1',version:7,status:'DRAFT',content:'先核对支付渠道失败事实。',evidence_ids:['ev1'],plan_id:'plan1'}];
  handler=path=>path.endsWith('/memories/m1/approve')?response({...state.memories[0],status:'APPROVED'}):null;
  const wrapper=await render(MerchantView);await button(wrapper,'核对并批准这条经验').trigger('click');const approval=wrapper.find('form.operation');
  await approval.trigger('submit');await flushPromises();expect(calls.some(item=>item.path.endsWith('/approve'))).toBe(false);
  expect(approval.text()).toContain('模型原草稿');expect(approval.find('textarea').element.value).toBe(state.memories[0].content);
  await approval.find('input[type=checkbox]').setValue(true);await approval.find('textarea').setValue('渠道拒付已确认，具体原因尚无证据。');
  expect(approval.find('input[type=checkbox]').element.checked).toBe(false);expect(approval.text()).toContain(state.memories[0].content);
  await approval.trigger('submit');await flushPromises();expect(calls.some(item=>item.path.endsWith('/approve'))).toBe(false);
  await approval.find('input[type=checkbox]').setValue(true);await approval.trigger('submit');await flushPromises();
  const write=calls.find(item=>item.path.endsWith('/memories/m1/approve'));
  expect(JSON.parse(write.options.body)).toEqual({expected_version:7,reviewed_content:'渠道拒付已确认，具体原因尚无证据。'});expect(write.options.headers['X-CSRF-Token']).toBe('scope-store');
});

it('uses an actual catalog SKU without requiring manual identifiers',async()=>{
  handler=path=>path.endsWith('/ads/campaigns')?response(campaign):null;
  const wrapper=await render(AdsView);await field(wrapper,'活动名称').setValue('SKU选择');await field(wrapper,'选择真实在售 SKU').setValue(JSON.stringify(['p1','hash1']));await wrapper.find('form').trigger('submit');await flushPromises();
  const body=JSON.parse(calls.find(item=>item.path.endsWith('/ads/campaigns')).options.body);expect(body.product_id).toBe('p1');expect(body.sku_key).toBe('hash1');expect(body).not.toHaveProperty('price_cents');
});

it('offers explicit resume for an exhausted campaign and sends its current version',async()=>{
  ads.campaigns[0].status='EXHAUSTED';ads.campaigns[0].version=8;
  ads.grants=[{grant_id:'g1',initial_plan_id:'plan1',initial_plan_version:3}];
  handler=path=>path.endsWith('/ads/actions')?response({business_status:'APPLIED'}):null;
  const wrapper=await render(AdsView);
  await field(wrapper,'执行所用授权').setValue('g1');await button(wrapper,'恢复活动').trigger('click');
  expect(calls.some(item=>item.path.endsWith('/ads/actions'))).toBe(false);
  await wrapper.find('form.operation').trigger('submit');await flushPromises();
  const body=JSON.parse(calls.find(item=>item.path.endsWith('/ads/actions')).options.body);
  expect(body.actions).toEqual([{action_type:'resume_campaign',campaign_id:'c1',expected_version:8}]);
});

it('switches only through server memberships, invalidates stale reads, and clears the old scoped form',async()=>{
  handler=path=>{if(path.endsWith('/scopes/select')){currentActor={...actor,execution_scope_id:'demo-1'};ads={...ads,campaigns:[]};return response({actor:currentActor,csrf_token:'scope-demo-1'});}};
  const wrapper=await render(App);await button(wrapper,'活动与授权').trigger('click');await flushPromises();await field(wrapper,'活动名称').setValue('不能带到另一范围');
  let resolveRead;const prior=handler;handler=(path,options)=>path==='/admin-api/assistant/merchant'?new Promise(resolve=>{resolveRead=resolve;}):prior(path,options);
  const stale=aiGet('/merchant').catch(error=>error);await flushPromises();
  await selectScope('demo-1');resolveRead(response({plans:[plan]}));expect((await stale).status).toBe(409);await flushPromises();
  expect(field(wrapper,'活动名称').element.value).toBe('');expect(session.value.actor.execution_scope_id).toBe('demo-1');
  expect(JSON.parse(calls.find(item=>item.path.endsWith('/scopes/select')).options.body)).toEqual({execution_scope_id:'demo-1'});
  handler=path=>path.endsWith('/merchant/runs')?response({state:'WAIT_OUTCOME'}):null;await aiWrite('/merchant/runs',{request_id:'next',objective:'新的范围',mode:'rule'});expect(calls.at(-1).options.headers['X-CSRF-Token']).toBe('scope-demo-1');
});


it('guides merchants to create a DRAFT campaign when planning is blocked',async()=>{
  handler=path=>path.endsWith('/merchant/runs')?response({error:'merchant_campaign_draft_required'},409):null;
  const wrapper=await render(MerchantView);
  await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(wrapper.text()).toContain('活动草稿');
  expect(wrapper.text()).toContain('去活动页创建草稿');
  await button(wrapper,'去活动页创建草稿').trigger('click');
  expect(wrapper.emitted('review-grant')).toBeTruthy();
});

it('asks to recover an uncertain plan instead of claiming a new run was saved',async()=>{
  handler=path=>path.endsWith('/merchant/runs')?response({state:'WAIT_OUTCOME',plan_recovery_required:true,latest_plan:plan}):null;
  const wrapper=await render(MerchantView);
  await field(wrapper,'目标和约束').setValue('继续核对实际结果');
  await wrapper.find('form').trigger('submit');await flushPromises();
  expect(wrapper.text()).toContain('请先恢复原计划回执');
  expect(wrapper.text()).not.toContain('请求已保存');
  expect(calls.some(item=>item.path.endsWith('/runs/undefined'))).toBe(false);
});
