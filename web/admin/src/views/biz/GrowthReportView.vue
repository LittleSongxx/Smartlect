<template>
  <div class="ai-page">
    <PageHeader title="增长报告" description="确定性数据快照（归因支付汇总 + AI 域活动计数由代码拼装）+ LLM 增长建议（禁编数字）；归因明细来自 attribution 汇总。">
      <template #actions>
        <el-button type="primary" :loading="busy" @click="generate">生成报告</el-button>
        <el-button :icon="Refresh" :loading="busy" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />

    <template v-if="latest">
      <div class="table-data-card">
        <h4 class="card-title">数据快照 · {{ timestamp(latest.updated_at) }}</h4>
        <div class="stat-row">
          <div class="stat"><span>成交净额(分)</span><strong>{{ latest.data.payments?.net_cents ?? '—' }}</strong></div>
          <div class="stat"><span>成交笔数</span><strong>{{ latest.data.payments?.conversions ?? '—' }}</strong></div>
          <div class="stat"><span>会话数</span><strong>{{ latest.data.ai_activity?.conversations ?? '—' }}</strong></div>
          <div class="stat"><span>转人工工单</span><strong>{{ latest.data.ai_activity?.support_tickets ?? '—' }}</strong></div>
        </div>
        <el-descriptions :column="2" border size="small" class="table-gap">
          <el-descriptions-item label="支付总额(分)">{{ latest.data.payments?.paid_cents ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="退款总额(分)">{{ latest.data.payments?.refunded_cents ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="已发布知识文档">{{ latest.data.ai_activity?.published_documents ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="运行状态分布"><span class="mono">{{ JSON.stringify(latest.data.ai_activity?.run_states || {}) }}</span></el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="table-data-card">
        <h4 class="card-title">LLM 增长建议</h4>
        <ol v-if="suggestions.length" class="suggestion-list">
          <li v-for="(item, index) in suggestions" :key="index">{{ item }}</li>
        </ol>
        <el-alert v-else type="info" :closable="false"
          :title="`建议未生成（${latest.model_error || '未配置'}）；确定性快照已保存。`" />
      </div>
    </template>
    <el-empty v-else description="还没有生成过增长报告" />

    <div class="table-data-card table-gap">
      <h4 class="card-title">历史</h4>
      <el-table :data="history" stripe size="small">
        <el-table-column label="净额(分)" width="110" align="right">
          <template #default="{ row }">{{ row.data?.payments?.net_cents ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="成交笔数" width="90" align="right">
          <template #default="{ row }">{{ row.data?.payments?.conversions ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="建议" width="70">
          <template #default="{ row }">
            <StatusTag :label="row.suggestions ? '有' : '无'" :tone="row.suggestions ? 'ok' : ''" />
          </template>
        </el-table-column>
        <el-table-column prop="model_label" label="模型" min-width="140" />
        <el-table-column label="时间" width="200">
          <template #default="{ row }">{{ timestamp(row.updated_at) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { aiGet, aiWrite, errorText, timestamp } from '@/api/client'

const latest = ref(null)
const history = ref([])
const busy = ref(false)
const error = ref('')

// The snapshot stores the suggestion list as a JSON array; older rows may carry the
// {"suggestions": [...]} envelope, so accept both and never let a parse error hide a list.
const suggestions = computed(() => {
  const raw = latest.value?.suggestions
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
      if (Array.isArray(parsed?.suggestions)) return parsed.suggestions
    } catch { /* a malformed snapshot reports "no suggestions" rather than breaking the page */ }
  }
  return []
})

const load = async () => {
  busy.value = true
  error.value = ''
  try {
    const view = await aiGet('/growthReport')
    latest.value = view.latest
    history.value = view.history || []
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const generate = async () => {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await aiWrite('/growthReport/generate', {})
    await load()
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped lang="scss">
.ai-page {

  .suggestion-list { margin: 0; padding-left: 1.4em; font-size: 13px; line-height: 2; }
}
</style>
