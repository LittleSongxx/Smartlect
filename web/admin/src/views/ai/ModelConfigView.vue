<template>
  <div class="ai-page">
    <PageHeader title="模型配置" description="在线切换当前端点可服务的白名单模型，保存后即时生效（约 5 秒内）。API Key 与端点仍由运行环境托管，不落库、不在本页展示。" />

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />
    <el-alert v-if="notice" type="success" :title="notice" show-icon closable class="table-gap" />

    <div class="table-data-card">
      <h4 class="card-title">运行状态（只读）</h4>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="调用模式">
          <StatusTag :label="modeText(info?.env?.model_mode)" tone="wait" />
        </el-descriptions-item>
        <el-descriptions-item label="对话模型 Key">
          <StatusTag :label="info?.env?.chat_key_configured ? '已配置' : '未配置'" :tone="info?.env?.chat_key_configured ? 'ok' : 'warn'" />
        </el-descriptions-item>
        <el-descriptions-item label="向量模型 Key">
          <StatusTag :label="info?.env?.embedding_key_configured ? '已配置' : '未配置'" :tone="info?.env?.embedding_key_configured ? 'ok' : 'warn'" />
        </el-descriptions-item>
        <el-descriptions-item label="当前生效模型"><span class="mono">{{ info?.chat?.model_id || '—' }}</span></el-descriptions-item>
        <el-descriptions-item label="环境默认模型"><span class="mono">{{ info?.chat?.env_model_id || '—' }}</span></el-descriptions-item>
        <el-descriptions-item label="向量模型"><span class="mono">{{ info?.env?.embedding_model || '—' }}</span></el-descriptions-item>
      </el-descriptions>
      <p class="muted-note">Key 的增改与端点切换属于部署操作：修改 run/model.env 后重启生效（运维流程，非本页能力）。</p>
    </div>

    <div class="table-data-card form-card">
      <h4 class="card-title">对话模型选择</h4>
      <p class="muted-note">仅列出当前端点可实际服务的模型；跨厂商切换需要更换端点（环境变量）。</p>
      <el-form label-width="110px" @submit.prevent="save">
        <el-form-item label="激活模型">
          <el-select v-model="form.model_id" style="width: 320px">
            <el-option v-for="option in info?.chat?.options || []" :key="option" :label="option" :value="option" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" maxlength="200" placeholder="例如：切快照锁版本，评测通过" style="width: 320px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="busy" :disabled="!form.model_id" @click="save">保存并激活</el-button>
          <el-button :loading="probing" @click="probe">测试连接</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="probeResult" :type="probeResult.ok ? 'success' : 'error'" :closable="false" class="table-gap"
        :title="probeResult.ok
          ? `连接正常：${probeResult.model_id}，${probeResult.latency_ms}ms，回复「${probeResult.reply}」`
          : `连接失败：${probeResult.error}（${probeResult.latency_ms}ms）`" />
      <p v-if="info?.chat?.updated_at" class="muted-note">
        上次修改：{{ timestamp(info.chat.updated_at) }}<span v-if="info.chat.updated_by"> · {{ info.chat.updated_by }}</span>
      </p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { aiGet, aiWrite, errorText, timestamp } from '@/api/client'
import { modeText } from '@/utils/growthDisplay'

const info = ref(null)
const form = reactive({ model_id: '', note: '' })
const busy = ref(false)
const probing = ref(false)
const error = ref('')
const notice = ref('')
const probeResult = ref(null)

const load = async () => {
  try {
    info.value = await aiGet('/models')
    form.model_id = info.value.chat.runtime_selected || info.value.chat.model_id
    form.note = info.value.chat.note || ''
  } catch (reason) {
    error.value = errorText(reason)
  }
}

const save = async () => {
  if (!form.model_id || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await aiWrite('/models/chat', { model_id: form.model_id, note: form.note || null })
    notice.value = `已激活 ${form.model_id}；运行中的调用将在数秒内切换到新模型。`
    await load()
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const probe = async () => {
  if (probing.value) return
  probing.value = true
  probeResult.value = null
  try {
    probeResult.value = await aiWrite('/models/testConnection', {})
  } catch (reason) {
    probeResult.value = { ok: false, error: errorText(reason), latency_ms: 0 }
  } finally {
    probing.value = false
  }
}

onMounted(load)
</script>

<style scoped lang="scss">
.ai-page {
  .table-gap {
    margin-bottom: 12px;
  }

  .form-card {
    margin-top: 12px;
  }

  .card-title {
    margin: 0 0 8px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
  }

  .muted-note {
    margin: 8px 0 0;
    font-size: 12px;
    line-height: 1.6;
    color: var(--text3);
  }

  .mono {
    font-family: var(--mono-font);
    font-size: 12px;
  }
}
</style>
