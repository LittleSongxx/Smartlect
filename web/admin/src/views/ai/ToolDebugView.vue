<template>
  <div class="ai-page">
    <PageHeader title="工具调试台" description="单工具直调试：入参表单化，结果结构化与原始 JSON 双展示。仅开放只读且无归因副作用的工具；每次调用都会作为一条「调试」运行留痕，可在运行浏览器中回查。" />

    <el-row :gutter="16">
      <el-col :xs="24" :md="10">
        <div class="table-data-card">
          <el-table :data="tools" size="small" highlight-current-row @current-change="selectTool">
            <el-table-column prop="name" label="工具" min-width="140">
              <template #default="{ row }">
                <span class="mono">{{ row.name }}</span>
                <el-tag v-if="row.debug_only" size="small" type="primary" class="tag-gap">调试专用</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="可调试" width="80" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.debuggable ? 'success' : 'info'">{{ row.debuggable ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="kind" label="类别" width="80" />
          </el-table>
          <p class="muted-note">写操作（提案/记忆/转人工）与带归因回执的推荐类工具不开放调试。</p>
        </div>
      </el-col>

      <el-col :xs="24" :md="14">
        <div class="table-data-card">
          <template v-if="current">
            <h4 class="card-title">{{ current.name }}</h4>
            <p class="muted-note">{{ current.description }}</p>
            <el-form label-width="120px" @submit.prevent="run">
              <el-form-item v-for="field in formFields" :key="field.name" :label="field.label">
                <el-input-number v-if="field.type === 'number'" v-model="form[field.name]" :min="0" :step="field.step || 1" style="width: 200px" />
                <el-input v-else v-model="form[field.name]" :placeholder="field.placeholder" maxlength="200" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="busy" @click="run">调用</el-button>
              </el-form-item>
            </el-form>

            <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />
            <template v-if="receipt">
              <h4 class="card-title">调用结果（运行 <span class="mono">{{ runId.slice(0, 10) }}</span>）</h4>
              <div class="result-summary">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item v-for="item in summaryRows" :key="item.label" :label="item.label">{{ item.value }}</el-descriptions-item>
                </el-descriptions>
              </div>
              <JsonCollapse title="原始 JSON" :value="receipt" />
            </template>
          </template>
          <el-empty v-else description="从左侧选择一个可调试的工具" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { aiGet, aiWrite, errorText } from '@/api/client'

// 三个可调试工具的表单定义；后端 inputSchema 为准，这里只做常用字段的表单化。
const TOOL_FORMS = {
  catalog_search: {
    fields: [
      { name: 'keyword', label: '关键字', type: 'text', placeholder: '如：保温杯' },
      { name: 'max_price_cents', label: '预算上限(分)', type: 'number', step: 100 },
      { name: 'category_id', label: '类目 ID', type: 'text', placeholder: '可选' },
      { name: 'limit', label: '返回数量', type: 'number', step: 1 },
    ],
    summarize: (data) => {
      const items = data?.items || []
      return [
        { label: '候选数量', value: String(items.length) },
        { label: '检索模式', value: data?.ranking_mode || '—' },
        { label: '空结果原因', value: data?.diagnostics?.empty_reason || '—' },
        { label: '算法版本', value: data?.algorithm_version || '—' },
      ]
    },
  },
  search_knowledge: {
    fields: [{ name: 'query', label: '检索问题', type: 'text', placeholder: '如：支持几天退款' }],
    summarize: (data) => {
      const results = data?.results || []
      return [
        { label: '召回条数', value: String(results.length) },
        { label: '检索通道', value: data?.retrieval?.strategy_version || '—' },
      ]
    },
  },
  get_product_offer: {
    fields: [{ name: 'productId', label: '商品 ID', type: 'text', placeholder: '如：19' }],
    summarize: (data) => [
      { label: '商品名', value: data?.productName || '—' },
      { label: '价格区间', value: data?.minPrice != null ? `${data.minPrice} ~ ${data.maxPrice}` : '—' },
    ],
  },
}

const tools = ref([])
const current = ref(null)
const form = reactive({})
const busy = ref(false)
const error = ref('')
const receipt = ref(null)
const runId = ref('')

const formFields = computed(() => (current.value ? TOOL_FORMS[current.value.name]?.fields || [] : []))
const summaryRows = computed(() => {
  if (!receipt.value || !current.value) return []
  const data = receipt.value.data ?? receipt.value
  return TOOL_FORMS[current.value.name]?.summarize?.(data) || []
})

const loadCatalog = async () => {
  try {
    tools.value = (await aiGet('/tools/catalog')).tools
  } catch (reason) {
    error.value = errorText(reason)
  }
}

const selectTool = (row) => {
  if (!row) return
  error.value = ''
  receipt.value = null
  current.value = row.debuggable ? row : null
  Object.keys(form).forEach((key) => delete form[key])
}

const run = async () => {
  if (!current.value || busy.value) return
  busy.value = true
  error.value = ''
  receipt.value = null
  try {
    const arguments_ = {}
    for (const field of formFields.value) {
      const value = form[field.name]
      if (value !== undefined && value !== null && value !== '') arguments_[field.name] = value
    }
    const result = await aiWrite('/tools/invoke', { name: current.value.name, arguments: arguments_ })
    runId.value = result.run_id
    receipt.value = result.receipt
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

onMounted(loadCatalog)
</script>

<style scoped lang="scss">
.ai-page {
  .table-gap {
    margin-bottom: 12px;
  }

  .mono {
    font-family: var(--mono-font);
    font-size: 12px;
  }

  .card-title {
    margin: 0 0 6px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
  }

  .muted-note {
    margin: 0 0 12px;
    font-size: 12px;
    line-height: 1.6;
    color: var(--text3);
  }

  .tag-gap {
    margin-left: 6px;
  }

  .result-summary {
    margin-bottom: 12px;
  }
}
</style>
