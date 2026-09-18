import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import Layout from '../src/views/Layout.vue';
import { createAdminRouter } from '../src/router.js';
import { aiGet, aiWrite, clearSession, selectScope, session } from '../src/api/client';
import ElementPlus from 'element-plus';
import { response, sharedComponents } from './helpers';

const actor = { subject_type: 'merchant', actor_id: 'm1', session_id: 's1', execution_scope_id: 'store', permissions: ['admin:legacy'] };
let calls, handler, currentActor; const wrappers=[];
const render = async (component, options={}) => {
  const global = { components: sharedComponents, plugins: [ElementPlus], ...(options.global || {}) };
  if (component === Layout) {
    const router = createAdminRouter(createMemoryHistory());
    await router.push(options.path || '/merchant');
    global.plugins = [...(global.plugins || []), router];
    const wrapper = mount(component, { ...options, global });
    wrappers.push(wrapper);
    await router.isReady();
    await flushPromises();
    return wrapper;
  }
  const wrapper = mount(component, { ...options, global });
  wrappers.push(wrapper);
  await flushPromises();
  return wrapper;
};
beforeEach(() => {
  clearSession(); currentActor={...actor}; session.value={actor:currentActor,csrf_token:'scope-store'}; calls=[]; handler=null;
  vi.stubGlobal('fetch',vi.fn(async(path,options={})=>{
    calls.push({path,options}); const handled=await handler?.(path,options); if(handled)return handled;
    if(path.endsWith('/session'))return response({actor:currentActor,csrf_token:`scope-${currentActor.execution_scope_id}`});
    if(path.endsWith('/scopes'))return response({items:[{execution_scope_id:'store',label:'店铺'},{execution_scope_id:'demo-1',label:'独立演示'}]});
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(()=>{wrappers.splice(0).forEach(wrapper=>wrapper.unmount());vi.unstubAllGlobals();});

it('retired merchant and ads pages stay reachable and marked disabled', async () => {
  const wrapper = await render(Layout, { path: '/merchant' });
  expect(wrapper.text()).toContain('已停用');
  expect(wrapper.text()).toContain('经营助手');
  expect(wrapper.text()).toContain('商家规划 Agent 已停用');
  await wrapper.vm.$router.push('/ads');
  await flushPromises();
  expect(wrapper.text()).toContain('付费广告投放已停用');
  expect(wrapper.text()).toContain('确定性推荐');
});

it('switches only through server memberships and invalidates stale reads', async () => {
  handler = path => {
    if (path.endsWith('/scopes/select')) {
      currentActor = { ...actor, execution_scope_id: 'demo-1' };
      return response({ actor: currentActor, csrf_token: 'scope-demo-1' });
    }
    return null;
  };
  await render(Layout, { path: '/knowledge' });
  let resolveRead;
  const prior = handler;
  handler = (path, options) => path === '/admin-api/assistant/merchant'
    ? new Promise(resolve => { resolveRead = resolve; })
    : prior(path, options);
  const stale = aiGet('/merchant').catch(error => error);
  await flushPromises();
  await selectScope('demo-1');
  resolveRead(response({ plans: [] }));
  expect((await stale).status).toBe(409);
  await flushPromises();
  expect(session.value.actor.execution_scope_id).toBe('demo-1');
  expect(JSON.parse(calls.find(item => item.path.endsWith('/scopes/select')).options.body)).toEqual({ execution_scope_id: 'demo-1' });
  handler = path => path.endsWith('/merchant/runs') ? response({ state: 'WAIT_OUTCOME' }) : null;
  await aiWrite('/merchant/runs', { request_id: 'next', objective: '新的范围', mode: 'rule' });
  expect(calls.at(-1).options.headers['X-CSRF-Token']).toBe('scope-demo-1');
});
