<template>
  <div class="ai-page">
    <PageHeader title="运行浏览器" description="Shopping / Merchant / MCP / 调试运行的留痕审计：模型调用、工具轨迹与成本。不含用户消息正文（30 天保留期后上下文会被清理）。">
      <template #actions>
        <el-button :icon="Refresh" :loading="busy" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <div class="search-panel">
      <el-form inline @submit.prevent="load">
        <el-form-item label="运行类型">
          <el-select v-model="filter.agent" style="width: 140px" @change="load">
            <el-option label="全部" value="" />
            <el-option v-for="kind in agentKindOptions" :key="kind.value" :label="kind.label" :value="kind.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filter.state" style="width: 160px" clearable @change="load">
            <el-option v-for="state in stateOptions" :key="state" :label="statusText(state)" :value="state" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="load">查询</el-button>
        </el-form-item>
      </el-form>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />

    <div class="table-data-card">
      <el-table v-loading="busy" :data="runs" stripe>
        <el-table-column prop="agent_run_id" label="运行" width="130">
          <template #default="{ row }">{{ row.agent_run_id.slice(0, 10) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="agentTagType(row.agent)">{{ agentLabel(row.agent) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <StatusTag :label="statusText(row.state)" :tone="badgeTone(row.state)" />
          </template>
        </el-table-column>
        <el-table-column label="会话主体" min-width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.conversation_subject }}:{{ row.conversation_actor }}</span>
          </template>
        </el-table-column>
        <el-table-column label="模型" width="110">
          <template #default="{ row }">{{ modeText(row.model_mode) }}</template>
        </el-table-column>
        <el-table-column label="Token 入/出" width="120" align="right">
          <template #default="{ row }">{{ row.usage.input_tokens }} / {{ row.usage.output_tokens }}</template>
        </el-table-column>
        <el-table-column label="费用(¥)" width="90" align="right">
          <template #default="{ row }">{{ row.usage.cost_estimate_cny ? row.usage.cost_estimate_cny.toFixed(4) : '—' }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="90" align="right">
          <template #default="{ row }">{{ row.duration_ms != null ? (row.duration_ms / 1000).toFixed(1) + 's' : '—' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ timestamp(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="当前范围还没有 Agent 运行记录" />
        </template>
      </el-table>
    </div>

    <el-dialog v-model="detailVisible" title="运行详情" width="860px" top="6vh">
      <template v-if="detail">
        <el-alert v-if="detail.context_empty" type="info" :closable="false"
          title="该运行没有可展示的上下文（尚未产生模型调用，或已超过 30 天保留期被清理）" class="table-gap" />
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="运行 ID"><span class="mono">{{ detail.agent_run_id }}</span></el-descriptions-item>
          <el-descriptions-item label="类型">{{ agentLabel(detail.agent) }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusText(detail.state) }}</el-descriptions-item>
          <el-descriptions-item label="模型模式">{{ modeText(detail.model_mode) }}</el-descriptions-item>
          <el-descriptions-item label="提示词版本"><span class="mono">{{ detail.context.prompt_version || '—' }}</span></el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ timestamp(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="会话"><span class="mono">{{ detail.conversation_subject }}:{{ detail.conversation_actor }}</span></el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detail.duration_ms != null ? (detail.duration_ms / 1000).toFixed(1) + 's' : '—' }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="detail.context.skill_versions">
          <DetailText title="技能版本" :text="detail.context.skill_versions" />
        </template>

        <div v-if="detail.model_attempts.length" class="detail-section">
          <h4>模型调用（{{ detail.model_attempts.length }} 次）</h4>
          <el-table :data="detail.model_attempts" stripe size="small">
            <el-table-column label="模型" min-width="140">
              <template #default="{ row }">{{ row.model_id || row.model || '—' }}</template>
            </el-table-column>
            <el-table-column label="输入 Token" width="100" align="right">
              <template #default="{ row }">{{ row.usage?.input_tokens ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="输出 Token" width="100" align="right">
              <template #default="{ row }">{{ row.usage?.output_tokens ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="费用(¥)" width="90" align="right">
              <template #default="{ row }">{{ row.cost_estimate_cny != null ? row.cost_estimate_cny.toFixed(4) : '—' }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="90" align="right">
              <template #default="{ row }">{{ row.latency_ms != null ? row.latency_ms + 'ms' : '—' }}</template>
            </el-table-column>
          </el-table>
        </div>

        <div v-if="detail.tool_calls.length" class="detail-section">
          <h4>工具调用（{{ detail.tool_calls.length }} 次）</h4>
          <el-table :data="detail.tool_calls" stripe size="small">
            <el-table-column prop="tool_name" label="工具" min-width="140" />
            <el-table-column prop="outcome" label="结果" width="150" />
            <el-table-column label="参数" min-width="220">
              <template #default="{ row }">
                <JsonCollapse title="入参" :value="row.arguments" />
              </template>
            </el-table-column>
            <el-table-column label="回执" min-width="220">
              <template #default="{ row }">
                <JsonCollapse title="回执" :value="row.receipt" />
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-if="detail.events.length" class="detail-section">
          <h4>事件时间线</h4>
          <el-timeline>
            <el-timeline-item v-for="event in detail.events" :key="event.sequence" :timestamp="timestamp(event.created_at)">
              <strong>{{ event.event_type }}</strong>
              <JsonCollapse v-if="event.data && Object.keys(event.data).length" title="事件数据" :value="event.data" />
            </el-timeline-item>
          </el-timeline>
        </div>

        <DetailText title="决策记录" :text="detail.result.decision" empty-text="该运行没有决策记录" />
        <DetailText title="检查结果" :text="detail.result.checks" empty-text="该运行没有检查记录" />
        <p v-if="detail.context_hidden_keys && detail.context_hidden_keys.length" class="muted-note">
          以下上下文字段出于隐私未展示：{{ detail.context_hidden_keys.join('、') }}
        </p>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { aiGet, errorText, timestamp } from '@/api/client'
import { statusText, modeText, badgeTone } from '@/utils/growthDisplay'

const agentKindOptions = [
  { value: 'shopping', label: '导购' },
  { value: 'merchant', label: '经营' },
  { value: 'mcp', label: 'MCP' },
  { value: 'debug', label: '调试' },
]
const stateOptions = ['RUNNING', 'WAIT_USER', 'WAIT_OUTCOME', 'COMPLETED', 'FAILED']

const filter = reactive({ agent: '', state: '' })
const runs = ref([])
const busy = ref(false)
const error = ref('')
const detailVisible = ref(false)
const detail = ref(null)

const agentLabel = (value) => ({ shopping: '导购', merchant: '经营', mcp: 'MCP', debug: '调试' }[value] || value)
const agentTagType = (value) => ({ shopping: 'success', merchant: 'warning', mcp: 'info', debug: 'primary' }[value] || 'info')

const load = async () => {
  busy.value = true
  error.value = ''
  try {
    const params = {}
    if (filter.agent) params.agent = filter.agent
    if (filter.state) params.state = filter.state
    const query = new URLSearchParams(params).toString()
    runs.value = (await aiGet('/runs' + (query ? `?${query}` : ''))).items
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const openDetail = async (row) => {
  try {
    detail.value = await aiGet(`/runs/${row.agent_run_id}`)
    detailVisible.value = true
  } catch (reason) {
    ElMessage.error(errorText(reason))
  }
}

onMounted(load)
</script>

<style scoped lang="scss">
.ai-page {

  .detail-section {
    margin-top: 16px;

    h4 {
      margin: 0 0 8px;
      font-size: 13px;
      font-weight: 600;
      color: var(--text2);
    }
  }
}
</style>
