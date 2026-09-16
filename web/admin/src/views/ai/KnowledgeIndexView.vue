<template>
  <div class="ai-page">
    <PageHeader title="知识索引" description="知识发布后的异步向量化流水线：任务进度与失败原因；发布入口在「知识库」页。">
      <template #actions>
        <el-button :icon="Refresh" :loading="busy" @click="refresh">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error || progress.error" :title="error || progress.error" show-icon :closable="false" class="table-gap" />

    <div v-if="runningJob" class="table-data-card progress-card">
      <div class="progress-head">
        <strong>正在索引：{{ runningJob.doc_id }} v{{ runningJob.version }}</strong>
        <span class="muted-note">这个页面关掉不影响后台执行；失败会从缺失切片续跑。</span>
      </div>
      <el-progress striped striped-flow :stroke-width="14" :percentage="percentage(runningJob)" />
      <div class="progress-meta">
        <span>已处理 {{ runningJob.processed_chunks }} / {{ runningJob.total_chunks }} 条切片</span>
        <span v-if="runningJob.message">{{ runningJob.message }}</span>
      </div>
    </div>

    <div class="table-data-card table-gap">
      <el-table v-loading="busy" :data="jobs" stripe size="small">
        <el-table-column prop="doc_id" label="文档" min-width="180" />
        <el-table-column label="版本" width="60">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <StatusTag :label="stateText(row.state)" :tone="stateTone(row.state)" />
          </template>
        </el-table-column>
        <el-table-column label="切片" width="110" align="right">
          <template #default="{ row }">{{ row.processed_chunks }}/{{ row.total_chunks }}</template>
        </el-table-column>
        <el-table-column prop="embedding_model" label="向量模型" width="150" />
        <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ timestamp(row.created_at) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有索引任务；在知识库页发布文档后这里会出现任务" />
        </template>
      </el-table>
    </div>

    <div class="table-data-card probe-card">
      <h4 class="card-title">检索试验台</h4>
      <p class="muted-note">与用户侧走完全相同的检索通道（含权限与混合排序）；用于验证新发布知识的召回效果。</p>
      <el-form inline @submit.prevent="runProbe">
        <el-form-item label="问题">
          <el-input v-model="probe.query" placeholder="如：支持几天退款" style="width: 320px" maxlength="200" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="probeBusy" @click="runProbe">检索</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="probeError" type="error" :title="probeError" show-icon :closable="false" class="table-gap" />
      <template v-if="probeResult">
        <el-descriptions :column="3" border size="small" class="table-gap">
          <el-descriptions-item label="答案状态">{{ probeResult.answer_status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="候选条数">{{ (probeResult.candidates || []).length }}</el-descriptions-item>
          <el-descriptions-item label="不可信指令">{{ probeResult.untrusted_instructions_detected ? '检测到' : '未检测到' }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="probeResult.citations || []" stripe size="small">
          <el-table-column prop="doc_id" label="文档" min-width="140" />
          <el-table-column prop="heading" label="小节" min-width="120" />
          <el-table-column prop="content" label="切片内容" min-width="320" show-overflow-tooltip />
          <el-table-column label="可信" width="80">
            <template #default="{ row }">
              <StatusTag :label="row.carries_untrusted_instructions ? '隔离' : '正常'" :tone="row.carries_untrusted_instructions ? 'warn' : 'ok'" />
            </template>
          </el-table-column>
        </el-table>
        <JsonCollapse title="检索元数据" :value="probeResult.retrieval" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { aiGet, aiWrite, errorText, timestamp } from '@/api/client'
import { useTaskProgress } from '@/composables/useTaskProgress'

const jobs = ref([])
const busy = ref(false)
const error = ref('')

const probe = reactive({ query: '' })
const probeBusy = ref(false)
const probeError = ref('')
const probeResult = ref(null)

const runningJob = computed(() => jobs.value.find((job) => job.state === 'PENDING' || job.state === 'RUNNING') || null)
const percentage = (job) => (job.total_chunks ? Math.round((job.processed_chunks / job.total_chunks) * 100) : 0)
const stateText = (value) => ({ PENDING: '排队中', RUNNING: '索引中', DONE: '已完成', FAILED: '失败' }[value] || value)
const stateTone = (value) => ({ PENDING: 'wait', RUNNING: 'wait', DONE: 'ok', FAILED: 'warn' }[value] || '')

const load = async () => {
  busy.value = true
  error.value = ''
  try {
    jobs.value = (await aiGet('/knowledgeIndex/jobs')).items
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

// 轮询走一个不吞异常的取数函数：连续失败由 useTaskProgress 计数后停下，
// 吞掉异常的话那条保护永远不会触发，坏掉的接口会被空转到 deadline。
const pollState = async () => {
  jobs.value = (await aiGet('/knowledgeIndex/jobs')).items
}

// 容错轮询：有进行中任务时每 2s 刷新，全部终态后自动停止单次加载
const progress = useTaskProgress(pollState, {
  intervalMs: 2000,
  deadlineMs: 30 * 60 * 1000,
  isDone: () => !runningJob.value,
})

// 刷新＝手动取数 + 重启轮询：终态后出现新任务（例如另一个标签页发布了文档）时恢复跟踪。
const refresh = async () => {
  await load()
  if (runningJob.value) progress.begin()
}

const runProbe = async () => {
  if (!probe.query.trim() || probeBusy.value) return
  probeBusy.value = true
  probeError.value = ''
  probeResult.value = null
  try {
    probeResult.value = await aiWrite('/knowledgeIndex/searchProbe', { query: probe.query.trim() })
  } catch (reason) {
    probeError.value = errorText(reason)
  } finally {
    probeBusy.value = false
  }
}

onMounted(async () => {
  await load()
  if (runningJob.value) progress.begin()
})</script>

<style scoped lang="scss">
.ai-page {
  .table-gap {
    margin-bottom: 12px;
  }

  .progress-card {
    padding: 14px 16px;
    margin-bottom: 12px;
  }

  .progress-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 10px;
  }

  .progress-meta {
    display: flex;
    gap: 16px;
    margin-top: 8px;
    font-size: 13px;
    color: var(--text2);
  }

  .card-title {
    margin: 0 0 6px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
  }

  .muted-note {
    margin: 0 0 10px;
    font-size: 12px;
    color: var(--text3);
  }

  .probe-card {
    margin-top: 12px;
  }
}
</style>
