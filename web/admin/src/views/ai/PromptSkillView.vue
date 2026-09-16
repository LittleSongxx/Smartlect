<template>
  <div class="ai-page">
    <PageHeader title="提示词与技能" description="系统提示词与 Skill 的版本管理：编辑生成新草稿版本，激活后下一次 Agent 运行即生效；回滚 = 重新激活历史版本。结构变更（新增技能、改工具白名单）仍需发版。">
      <template #actions>
        <el-button :icon="Refresh" :loading="busy" @click="loadKeys">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />
    <el-alert v-if="notice" type="success" :title="notice" show-icon closable class="table-gap" />

    <el-row :gutter="16">
      <el-col :xs="24" :md="8">
        <div class="table-data-card">
          <h4 class="card-title">模板清单</h4>
          <el-collapse v-model="openDomains">
            <el-collapse-item v-for="(items, domain) in domains" :key="domain" :title="domainLabel(domain)" :name="domain">
              <div v-for="item in items" :key="`${domain}:${item.kind}:${item.key}`" class="template-entry"
                :class="{ selected: selected && selected.domain === domain && selected.kind === item.kind && selected.key === item.key }"
                @click="select(domain, item)">
                <div class="entry-head">
                  <strong>{{ item.key === 'system' ? '系统提示词' : item.key }}</strong>
                  <StatusTag :label="kindLabel(item.kind)" tone="wait" />
                </div>
                <div class="entry-meta">v{{ item.latest }} · {{ item.versions }} 个版本</div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-col>

      <el-col :xs="24" :md="16">
        <div class="table-data-card">
          <template v-if="selected">
            <h4 class="card-title">{{ domainLabel(selected.domain) }} · {{ selected.key === 'system' ? '系统提示词' : selected.key }}</h4>
            <div class="table-data-card version-list">
              <el-table :data="versions" size="small" stripe highlight-current-row>
                <el-table-column label="版本" width="70">
                  <template #default="{ row }">v{{ row.version }}</template>
                </el-table-column>
                <el-table-column label="状态" width="90">
                  <template #default="{ row }">
                    <StatusTag :label="statusText(row.status)" :tone="row.status === 'active' ? 'ok' : row.status === 'draft' ? 'wait' : ''" />
                  </template>
                </el-table-column>
                <el-table-column prop="updated_by" label="修改人" width="110" />
                <el-table-column label="时间" width="160">
                  <template #default="{ row }">{{ timestamp(row.updated_at) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="170" fixed="right">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="viewBody(row)">查看</el-button>
                    <el-button v-if="row.status !== 'active'" link type="warning"
                      @click="activate(row)">{{ row.status === 'retired' ? '回滚到此版' : '激活' }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <el-divider content-position="left">编辑新版本（基于 v{{ baseVersion }}）</el-divider>
            <el-input v-model="editBody" type="textarea" :rows="selected.kind === 'skill' ? 14 : 12"
              class="editor" :placeholder="selected.kind === 'skill' ? 'Skill JSON（必须保持打包结构）' : '系统提示词文本'" />
            <div class="button-row">
              <el-button type="primary" :loading="busy" :disabled="!editBody.trim()" @click="saveDraft">保存为草稿</el-button>
              <el-button @click="loadBase" :disabled="busy">重置为当前激活版</el-button>
            </div>
            <p class="muted-note">保存草稿不会影响线上；激活后下一次 Agent 运行生效。Skill 保存时将做结构校验（保持打包版字段与 skill_id，版本号 semver）。</p>
          </template>
          <el-empty v-else description="从左侧选择一个模板" />
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="bodyVisible" :title="`版本内容 v${viewing?.version || ''}`" width="760px" top="6vh">
      <DetailText :text="viewingBody" />
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiGet, aiWrite, errorText, timestamp } from '@/api/client'

const domains = ref({})
const openDomains = reactive(['shopping'])
const selected = ref(null)
const versions = ref([])
const baseVersion = ref(null)
const editBody = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const bodyVisible = ref(false)
const viewing = ref(null)
const viewingBody = ref('')

const domainLabel = (value) => ({ shopping: '导购 Agent', merchant: '经营 Agent' }[value] || value)
const kindLabel = (value) => ({ system_prompt: '系统提示词', skill: '技能' }[value] || value)
const statusText = (value) => ({ active: '生效中', draft: '草稿', retired: '历史' }[value] || value)

const loadKeys = async () => {
  busy.value = true
  error.value = ''
  try {
    domains.value = (await aiGet('/prompts')).domains
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const select = async (domain, item) => {
  selected.value = { domain, kind: item.kind, key: item.key }
  notice.value = ''
  await loadVersions()
  await loadBase()
}

const loadVersions = async () => {
  const { domain, kind, key } = selected.value
  versions.value = (await aiGet(`/prompts/${domain}/${kind}/${encodeURIComponent(key)}/versions`)).items
}

const activeVersion = () => versions.value.find((item) => item.status === 'active')

const loadBase = async () => {
  const { domain, kind, key } = selected.value
  const active = activeVersion()
  baseVersion.value = active ? active.version : versions.value[0]?.version
  if (baseVersion.value == null) return
  editBody.value = (await aiGet(`/prompts/${domain}/${kind}/${encodeURIComponent(key)}/${baseVersion.value}`)).body
}

const viewBody = async (row) => {
  const { domain, kind, key } = selected.value
  viewing.value = row
  viewingBody.value = (await aiGet(`/prompts/${domain}/${kind}/${encodeURIComponent(key)}/${row.version}`)).body
  bodyVisible.value = true
}

const saveDraft = async () => {
  if (!selected.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    let body = editBody.value
    if (selected.value.kind === 'skill') {
      JSON.parse(body) // local syntax gate; server re-validates structure
    }
    const created = await aiWrite(`/prompts/${selected.value.domain}/${selected.value.kind}/${encodeURIComponent(selected.value.key)}`, { body })
    notice.value = `已保存草稿 v${created.version}；核对无误后点击「激活」生效。`
    await loadVersions()
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const activate = async (row) => {
  if (!selected.value || busy.value) return
  const label = `${domainLabel(selected.value.domain)} ${selected.value.key === 'system' ? '系统提示词' : selected.value.key} v${row.version}`
  try {
    await ElMessageBox.confirm(`确认将 ${label} 设为生效版本？下一次 Agent 运行即使用该文本。`, '激活确认', { type: 'warning' })
  } catch {
    return
  }
  busy.value = true
  error.value = ''
  try {
    await aiWrite(`/prompts/${selected.value.domain}/${selected.value.kind}/${encodeURIComponent(selected.value.key)}/${row.version}/activate`, {})
    notice.value = `${label} 已激活。`
    await loadVersions()
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

onMounted(loadKeys)
</script>

<style scoped lang="scss">
.ai-page {
  .table-gap {
    margin-bottom: 12px;
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

  .version-list {
    margin-bottom: 8px;
    box-shadow: none;
  }

  .editor {
    margin-bottom: 8px;

    :deep(textarea) {
      font-family: var(--mono-font);
      font-size: 12px;
    }
  }

  .button-row {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }

  .template-entry {
    padding: 8px 10px;
    border-radius: var(--card-radius);
    cursor: pointer;
    transition: background 0.15s;

    &:hover {
      background: var(--primary-muted);
    }

    &.selected {
      background: var(--primary-soft);
    }

    .entry-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }

    .entry-meta {
      margin-top: 2px;
      font-size: 12px;
      color: var(--text3);
    }
  }
}
</style>
