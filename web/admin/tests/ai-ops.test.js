import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import AgentRunsView from '../src/views/ai/AgentRunsView.vue'
import ToolDebugView from '../src/views/ai/ToolDebugView.vue'
import { response, installJsdomPolyfills } from './helpers'
import { clearSession, session } from '../src/api/client'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import PageHeader from '../src/components/PageHeader.vue'
import StatusTag from '../src/components/StatusTag.vue'
import DetailText from '../src/components/DetailText.vue'
import JsonCollapse from '../src/components/JsonCollapse.vue'

installJsdomPolyfills()

const actor = { subject_type: 'merchant', actor_id: 'm1', session_id: 's1', execution_scope_id: 'store', permissions: ['admin:legacy'] }
const run = {
  agent_run_id: 'a'.padEnd(32, '1'), agent: 'shopping', state: 'COMPLETED', model_mode: 'live',
  conversation_subject: 'user', conversation_actor: 'u-9', created_at: '2026-09-16T10:00:00Z', updated_at: '2026-09-16T10:00:02Z',
  duration_ms: 2000, context_empty: false, context: { prompt_version: 'shopping-react-v24' }, context_hidden_keys: ['mission'],
  usage: { input_tokens: 30, output_tokens: 12, cost_estimate_cny: 0.01, model_attempts: 1 },
  result: { decision: { answer_status: 'answered' }, checks: [{ id: 'policy_grounding_has_this_turn_citation', status: 'passed' }] },
}
const detail = {
  ...run, tool_calls: [{ tool_name: 'search_knowledge', outcome: 'business_completed', arguments: { query: '退款' }, receipt: { data: {} } }],
  events: [{ sequence: 1, event_type: 'tool_started', data: { name: 'search_knowledge' }, created_at: '2026-09-16T10:00:00Z' }],
  model_attempts: [{ model_id: 'qwen3.7-plus', usage: { input_tokens: 30, output_tokens: 12 }, cost_estimate_cny: 0.01 }],
}
const catalog = { tools: [
  { name: 'catalog_search', description: '调试专用检索', permission: 'admin:legacy', kind: 'read', debuggable: true, debug_only: true },
  { name: 'search_knowledge', description: '检索已发布政策', permission: 'shopping:read', kind: 'read', debuggable: true },
  { name: 'propose_order', description: '下单提案', permission: 'orders:write', kind: 'proposal', debuggable: false },
] }

let calls, handler
beforeEach(() => {
  clearSession()
  session.value = { actor, csrf_token: 'token-1' }
  calls = []
  handler = null
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options })
    const handled = await handler?.(path, options)
    if (handled) return handled
    if (path.endsWith('/session')) return response({ actor, csrf_token: 'token-1' })
    if (path.endsWith('/assistant/runs') || /\/runs\?/.test(path)) return response({ items: [run] })
    if (/\/runs\/[a1]+/.test(path)) return response(detail)
    if (path.endsWith('/tools/catalog')) return response(catalog)
    if (path.endsWith('/tools/invoke')) return response({ run_id: 'b'.padEnd(32, '2'), receipt: { data: { items: [], diagnostics: { empty_reason: 'no_eligible_sku' }, ranking_mode: 'content_rule' } } })
    throw new Error(`Unexpected request: ${path}`)
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

const mountView = async (component) => {
  const wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [ElementPlus],
      components: { PageHeader, StatusTag, DetailText, JsonCollapse },
    },
  })
  await flushPromises()
  return wrapper
}

it('runs browser lists runs with usage and opens the audit detail', async () => {
  const wrapper = await mountView(AgentRunsView)
  expect(wrapper.text()).toContain('导购')
  expect(wrapper.text()).toContain('30 / 12')
  await wrapper.findAll('button').find((item) => item.text() === '详情').trigger('click')
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
  expect(calls.some((item) => /\/runs\/[a1]+$/.test(item.path))).toBe(true)
  const dialog = document.body.textContent || ''
  expect(dialog).toContain('search_knowledge')
  expect(dialog).toContain('shopping-react-v24')
  expect(dialog).toContain('出于隐私未展示')
})

it('tool debug lists catalog, blocks non-debuggable tools and posts only filled arguments', async () => {
  const wrapper = await mountView(ToolDebugView)
  expect(wrapper.text()).toContain('propose_order')
  const table = wrapper.findComponent({ name: 'ElTable' })
  table.vm.$emit('current-change', catalog.tools[0])
  await flushPromises()
  await wrapper.find('input[type="number"]').setValue('5000')
  await wrapper.findAll('button').find((item) => item.text() === '调用').trigger('click')
  await flushPromises()
  const invoke = calls.find((item) => item.path.endsWith('/tools/invoke'))
  expect(JSON.parse(invoke.options.body)).toEqual({ name: 'catalog_search', arguments: { max_price_cents: 5000 } })
  expect(wrapper.text()).toContain('候选数量')
  expect(wrapper.text()).toContain('no_eligible_sku')

  // Non-debuggable selection clears the form panel instead of building a write surface.
  table.vm.$emit('current-change', catalog.tools[2])
  await flushPromises()
  expect(wrapper.text()).toContain('从左侧选择一个可调试的工具')
})

it('knowledge index page polls a running job and stops at terminal state', async () => {
  const { default: KnowledgeIndexView } = await import('../src/views/ai/KnowledgeIndexView.vue')
  let jobState = 'RUNNING'
  handler = (path) => {
    if (path.endsWith('/knowledgeIndex/jobs')) {
      return response({ items: [{ job_id: 'j1', doc_id: 'doc', version: 1, state: jobState, total_chunks: 10, processed_chunks: 4, message: null, created_at: '2026-09-16T10:00:00Z' }] })
    }
    return null
  }
  const wrapper = await mountView(KnowledgeIndexView)
  expect(wrapper.text()).toContain('正在索引：doc v1')
  expect(wrapper.text()).toContain('已处理 4 / 10 条切片')
  jobState = 'DONE'  // flip before the next 2s poll tick fires
  await new Promise((resolve) => setTimeout(resolve, 2300))
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(wrapper.text()).toContain('已完成')
  wrapper.unmount()
})

it('knowledge publish surfaces the async job notice', async () => {
  const { default: KnowledgeView } = await import('../src/views/KnowledgeView.vue')
  handler = (path, options) => {
    if (path.endsWith('/knowledge')) return response([{ doc_id: 'd1', version: 2, title: '文档', status: 'DRAFT', acl: 'MERCHANT', valid_from: '2026-01-01T00:00:00Z', valid_until: '2030-01-01T00:00:00Z' }])
    if (path.endsWith('/d1/2')) return response({ doc_id: 'd1', version: 2, title: '文档', status: 'DRAFT', acl: 'MERCHANT', body: '正文', checksum: 'c', source_uri: 's', valid_from: '2026-01-01T00:00:00Z', valid_until: '2030-01-01T00:00:00Z' })
    if (path.endsWith('/d1/2/publish')) return response({ job_id: 'job123456', state: 'PENDING', total_chunks: 3 })
    return null
  }
  const wrapper = await mountView(KnowledgeView)
  await wrapper.findAll('button').find((item) => item.text() === '核对发布').trigger('click')
  await flushPromises()
  await wrapper.find('form.operation').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('向量索引任务 job12345')
  wrapper.unmount()
})
