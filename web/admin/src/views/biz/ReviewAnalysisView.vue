<template>
  <div class="ai-page">
    <PageHeader title="评价分析" description="基于订单评价的确定性统计（星级分布/均分/好评率/情绪档由代码计算），LLM 仅基于真实评价生成优点/问题/关键词/建议四项洞察。">
      <template #actions>
        <el-button :icon="Refresh" :loading="busy" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />

    <div class="search-panel">
      <el-form inline @submit.prevent="analyze">
        <el-form-item label="商品 ID">
          <el-input v-model="productId" placeholder="输入商品 ID" style="width: 220px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="busy" :disabled="!productId.trim()" @click="analyze">生成分析</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="current" class="table-data-card">
      <h4 class="card-title">商品 {{ current.product_id }} · {{ sentimentText }}</h4>
      <div class="stat-row">
        <div class="stat"><span>评价数</span><strong>{{ current.stats.total }}</strong></div>
        <div class="stat"><span>均分</span><strong>{{ current.stats.average }}</strong></div>
        <div class="stat"><span>好评率</span><strong>{{ (current.stats.positive_rate * 100).toFixed(1) }}%</strong></div>
        <div class="stat"><span>好评/中评/差评</span><strong>{{ current.stats.good }}/{{ current.stats.mid }}/{{ current.stats.bad }}</strong></div>
      </div>
      <template v-if="current.insights">
        <el-divider content-position="left">LLM 洞察（基于真实评价）</el-divider>
        <el-row :gutter="12">
          <el-col v-for="group in insightGroups" :key="group.key" :xs="24" :md="12">
            <div class="insight-block">
              <h5>{{ group.label }}</h5>
              <ul><li v-for="item in group.items" :key="item">{{ item }}</li></ul>
            </div>
          </el-col>
        </el-row>
      </template>
      <el-alert v-else type="info" :closable="false" class="table-gap"
        :title="`洞察未生成（${current.insight_error || '未配置'}）；确定性统计已保存。`" />
      <p class="muted-note">分析时间 {{ timestamp(current.updated_at) }} · 重新生成会覆盖当前快照</p>
    </div>

    <div class="table-data-card table-gap">
      <h4 class="card-title">历史分析</h4>
      <el-table :data="items" stripe size="small">
        <el-table-column prop="product_id" label="商品" min-width="120" />
        <el-table-column label="情绪档" width="100">
          <template #default="{ row }">
            <StatusTag :label="sentimentLabel(row.stats?.sentiment)" :tone="sentimentTone(row.stats?.sentiment)" />
          </template>
        </el-table-column>
        <el-table-column label="评价数" width="80" align="right">
          <template #default="{ row }">{{ row.comment_count }}</template>
        </el-table-column>
        <el-table-column label="均分" width="80" align="right">
          <template #default="{ row }">{{ row.stats?.average ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="洞察" width="80">
          <template #default="{ row }">
            <StatusTag :label="row.insights ? '有' : '无'" :tone="row.insights ? 'ok' : ''" />
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ timestamp(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="show(row)">查看</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="还没有生成过评价分析" /></template>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { aiGet, aiWrite, errorText, timestamp } from '@/api/client'

const productId = ref('')
const items = ref([])
const current = ref(null)
const busy = ref(false)
const error = ref('')

const sentimentText = computed(() => sentimentLabel(current.value?.stats?.sentiment))
const sentimentLabel = (value) => ({ POSITIVE: '整体好评', NEUTRAL: '褒贬不一', NEGATIVE: '整体偏差' }[value] || '未知')
const sentimentTone = (value) => ({ POSITIVE: 'ok', NEUTRAL: 'wait', NEGATIVE: 'warn' }[value] || '')

const insightGroups = computed(() => {
  const insights = current.value?.insights || {}
  return [
    { key: 'strengths', label: '优点', items: insights.strengths || [] },
    { key: 'problems', label: '问题', items: insights.problems || [] },
    { key: 'keywords', label: '关键词', items: insights.keywords || [] },
    { key: 'suggestions', label: '改进建议', items: insights.suggestions || [] },
  ]
})

const load = async () => {
  busy.value = true
  error.value = ''
  try {
    items.value = (await aiGet('/reviewAnalysis')).items
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const analyze = async () => {
  if (!productId.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    current.value = await aiWrite(`/reviewAnalysis/product/${productId.value.trim()}`, {})
    await load()
  } catch (reason) {
    error.value = errorText(reason)
  } finally {
    busy.value = false
  }
}

const show = async (row) => {
  try {
    current.value = await aiGet(`/reviewAnalysis/product/${row.product_id}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (reason) {
    ElMessage.error(errorText(reason))
  }
}

onMounted(load)
</script>

<style scoped lang="scss">
.ai-page {

  .insight-block {
    border: 1px solid var(--header-border); border-radius: var(--card-radius); padding: 10px 14px; margin-bottom: 12px;
    h5 { margin: 0 0 6px; font-size: 13px; color: var(--text2); }
    ul { margin: 0; padding-left: 1.2em; font-size: 13px; line-height: 1.8; }
  }
}
</style>
