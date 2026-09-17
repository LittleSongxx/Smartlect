import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import AgentRunsView from '../src/views/ai/AgentRunsView.vue'
import ToolDebugView from '../src/views/ai/ToolDebugView.vue'
import { response, installJsdomPolyfills, sharedComponents } from './helpers'
import { clearSession, session } from '../src/api/client'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'

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
      components: sharedComponents,
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

it('knowledge view imports product drafts and filters by source', async () => {
  const { default: KnowledgeView } = await import('../src/views/KnowledgeView.vue')
  handler = (path, options) => {
    if (path.endsWith('/knowledge') && options?.method !== 'POST') {
      return response([
        { doc_id: 'manual-1', version: 1, title: '人工政策', status: 'PUBLISHED', acl: 'PUBLIC', source_type: 'MANUAL', valid_from: '2026-01-01T00:00:00Z', valid_until: '2030-01-01T00:00:00Z' },
        { doc_id: 'product-p1', version: 2, title: '商品知识：保温杯', status: 'DRAFT', acl: 'PUBLIC', source_type: 'PRODUCT_AUTO', valid_from: '2026-01-01T00:00:00Z', valid_until: '2030-01-01T00:00:00Z' },
      ])
    }
    if (path.endsWith('/knowledgeImport/products')) {
      return response({ imported: ['p1'], skipped: [], failed: [], published_pending_review: [], requested: 1, truncated: false, note: '' })
    }
    return null
  }
  const wrapper = await mountView(KnowledgeView)
  expect(wrapper.text()).toContain('人工政策')
  expect(wrapper.text()).toContain('商品知识：保温杯')
  expect(wrapper.text()).toContain('商品自动')

  await wrapper.findAll('button').find((item) => item.text() === '从商品导入').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('全部在售商品')
  expect(wrapper.text()).toContain('指定商品 ID')
  expect(wrapper.findComponent({ name: 'ElRadioGroup' }).exists()).toBe(true)
  await wrapper.find('form.operation').trigger('submit')
  await flushPromises()
  const invoke = calls.filter((item) => item.path.endsWith('/knowledgeImport/products'))
  expect(invoke).toHaveLength(1)
  expect(JSON.parse(invoke[0].options.body)).toEqual({})  // default 全部在售
  expect(wrapper.text()).toContain('导入 1 个')
  wrapper.unmount()
})

it('model config page shows env badges, saves within endpoint family and probes connection', async () => {
  const { default: ModelConfigView } = await import('../src/views/ai/ModelConfigView.vue')
  handler = (path) => {
    if (path.endsWith('/assistant/models') && !path.includes('/chat') && !path.includes('/testConnection')) {
      return response({ chat: { model_id: 'qwen3.7-plus', runtime_selected: null, env_model_id: 'qwen3.7-plus',
        options: ['qwen3.7-plus', 'qwen3.7-plus-2026-05-26'], updated_by: null, updated_at: null, note: null },
        env: { chat_key_configured: true, chat_base_url: true, embedding_key_configured: false,
          embedding_model: 'text-embedding-v4', model_mode: 'live' } })
    }
    if (path.endsWith('/models/chat')) return response({ model_id: 'qwen3.7-plus-2026-05-26' })
    if (path.endsWith('/models/testConnection')) return response({ ok: true, model_id: 'qwen3.7-plus', latency_ms: 640, reply: 'OK' })
    return null
  }
  const wrapper = await mountView(ModelConfigView)
  expect(wrapper.text()).toContain('真实模型 live')
  expect(wrapper.text()).toContain('已配置')
  expect(wrapper.text()).toContain('未配置')

  const select = wrapper.findComponent({ name: 'ElSelect' })
  select.vm.$emit('update:modelValue', 'qwen3.7-plus-2026-05-26')
  await flushPromises()
  await wrapper.findAll('button').find((item) => item.text() === '保存并激活').trigger('click')
  await flushPromises()
  const saved = calls.find((item) => item.path.endsWith('/models/chat'))
  expect(JSON.parse(saved.options.body).model_id).toBe('qwen3.7-plus-2026-05-26')
  expect(wrapper.text()).toContain('已激活')

  await wrapper.findAll('button').find((item) => item.text() === '测试连接').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('640ms')
  wrapper.unmount()
})

it('prompt skill view edits a draft and activates a rollback with confirmation', async () => {
  const { default: PromptSkillView } = await import('../src/views/ai/PromptSkillView.vue')
  handler = (path, options) => {
    if (path.endsWith('/prompts') || /\/prompts\?/.test(path)) {
      return response({ domains: { shopping: [
        { kind: 'system_prompt', key: 'system', versions: 2, latest: 25, active_count: 1 },
        { kind: 'skill', key: 'support_policy', versions: 1, latest: 1, active_count: 1 },
      ], merchant: [] } })
    }
    if (path.endsWith('/prompts/shopping/system_prompt/system/versions')) {
      return response({ items: [
        { id: 3, version: 26, status: 'draft', updated_by: 'boss', updated_at: '2026-09-16T12:00:00Z', size: 101 },
        { id: 2, version: 25, status: 'active', updated_by: 'boss', updated_at: '2026-09-16T10:00:00Z', size: 100 },
        { id: 1, version: 24, status: 'retired', updated_by: 'code-seed', updated_at: '2026-09-15T10:00:00Z', size: 99 },
      ] })
    }
    if (/\/prompts\/shopping\/system_prompt\/system\/\d+$/.test(path)) return response({ body: '基础策略文本' })
    if (path.endsWith('/prompts/shopping/system_prompt/system') && options?.method === 'POST') {
      return response({ domain: 'shopping', kind: 'system_prompt', key: 'system', version: 26, status: 'draft' })
    }
    if (path.endsWith('/system/24/activate')) return response({ version: 24, status: 'active' })
    return null
  }
  const wrapper = await mountView(PromptSkillView)
  expect(wrapper.text()).toContain('导购 Agent')
  await wrapper.find('.template-entry').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('生效中')
  expect(editValue(wrapper)).toContain('基础策略文本')

  const before = editValue(wrapper) + '\n新增一条规则。'
  await wrapper.find('textarea').setValue(before)
  await wrapper.findAll('button').find((item) => item.text() === '保存为草稿').trigger('click')
  await flushPromises()
  const draft = calls.find((item) => item.path.endsWith('/prompts/shopping/system_prompt/system') && item.options.method === 'POST')
  expect(JSON.parse(draft.options.body).body).toContain('新增一条规则')

  // rollback confirmation cancels without hitting the endpoint
  await wrapper.findAll('button').find((item) => item.text() === '回滚到此版').trigger('click')
  await flushPromises()
  expect(calls.some((item) => item.path.endsWith('/24/activate'))).toBe(false)
  wrapper.unmount()
})

const editValue = (wrapper) => wrapper.find('textarea').element.value

it('review analysis page generates deterministic stats and lists history', async () => {
  const { default: ReviewAnalysisView } = await import('../src/views/biz/ReviewAnalysisView.vue')
  handler = (path, options) => {
    if (path.endsWith('/reviewAnalysis') && options?.method !== 'POST') {
      // The list endpoint returns insights_json decoded as `insights`; a row with narration
      // must read as "有", which is why the field is part of the list projection.
      return response({ items: [
        { product_id: 'p1', comment_count: 2, insights: null,
          stats: { total: 2, good: 2, mid: 0, bad: 0, average: 4.5, positive_rate: 1, sentiment: 'POSITIVE' },
          updated_at: '2026-09-16T10:00:00Z' },
        { product_id: 'p2', comment_count: 3, insights: { strengths: ['轻'], problems: [], keywords: ['轻'], suggestions: [] },
          stats: { total: 3, good: 1, mid: 1, bad: 1, average: 3.0, positive_rate: 0.3333, sentiment: 'NEGATIVE' },
          updated_at: '2026-09-16T09:00:00Z' }] })
    }
    if (path.endsWith('/reviewAnalysis/product/p1')) {
      return response({ product_id: 'p1', comment_count: 2, insights: { strengths: ['保温好'], problems: [], keywords: ['保温'], suggestions: ['继续'] },
        stats: { total: 2, good: 2, mid: 0, bad: 0, average: 4.5, positive_rate: 1, sentiment: 'POSITIVE' },
        insight_error: null, updated_at: '2026-09-16T10:00:00Z' })
    }
    return null
  }
  const wrapper = await mountView(ReviewAnalysisView)
  expect(wrapper.text()).toContain('整体好评')
  expect(wrapper.findAll('tbody tr')[0].text()).toContain('无')
  expect(wrapper.findAll('tbody tr')[1].text()).toContain('有')
  await wrapper.find('input').setValue('p1')
  await wrapper.findAll('button').find((item) => item.text() === '生成分析').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('保温好')
  wrapper.unmount()
})

it('growth report page renders snapshot numbers and parses stored suggestions', async () => {
  const { default: GrowthReportView } = await import('../src/views/biz/GrowthReportView.vue')
  // The snapshot stores the suggestion list as a JSON array; the older {"suggestions": ...}
  // envelope and a null column are both covered so neither shape hides a real list.
  const report = (suggestions) => ({ latest: {
    data: { payments: { net_cents: 800, conversions: 3, paid_cents: 1000, refunded_cents: 200 },
      ai_activity: { conversations: 9, support_tickets: 1, published_documents: 5, run_states: { COMPLETED: 4, FAILED: 1, WAIT_USER: 0 } } },
    suggestions, model_label: 'qwen3.7-plus@live', model_error: null, updated_at: '2026-09-16T10:00:00Z' },
    history: [] })

  handler = () => response(report('["增加导购入口", "跟进差评商品", "扩充知识库"]'))
  const wrapper = await mountView(GrowthReportView)
  expect(wrapper.text()).toContain('800')
  expect(wrapper.text()).toContain('增加导购入口')
  expect(wrapper.text()).toContain('5')  // published documents
  // 运行状态是计数字典：页面上要读成"已完成 4 · 失败 1"，不能露出原始 JSON；计数为 0 的不显示
  expect(wrapper.text()).toContain('已完成 4')
  expect(wrapper.text()).toContain('失败 1')
  expect(wrapper.text()).not.toContain('{"COMPLETED"')
  expect(wrapper.text()).not.toContain('等待用户确认 0')
  wrapper.unmount()

  handler = () => response(report('{"suggestions": ["改写客服话术"]}'))
  const legacy = await mountView(GrowthReportView)
  expect(legacy.text()).toContain('改写客服话术')
  legacy.unmount()

  handler = () => response(report(null))
  const empty = await mountView(GrowthReportView)
  expect(empty.text()).toContain('建议未生成')
  empty.unmount()
})

it('growth 业务错误码给中文提示，不把机器码摆给管理员', async () => {
  const { errorText } = await import('../src/api/client')
  expect(errorText(new Error('no_comments'))).toBe('这件商品还没有评价，先有评价才能生成分析。')
  expect(errorText(new Error('invalid_suggestions'))).toContain('结构不符合约定')
  expect(errorText(new Error('something_else'))).toBe('something_else')  // 未知码原样透出，便于排查
})
