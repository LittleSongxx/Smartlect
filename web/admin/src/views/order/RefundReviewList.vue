<template>
  <PageHeader title="退款复核" description="退款申请的人工审核与处理。" />
  <div class="search-panel">
    <el-form @submit.prevent>
      <el-row :gutter="10">
        <el-col :span="6">
          <el-button type="primary" @click="loadDataList">刷新待复核</el-button>
        </el-col>
      </el-row>
    </el-form>
  </div>
  <el-card class="table-data-card">
    <div class="table-panel">
      <Table
        ref="tableInfoRef"
        :columns="columns"
        :fetch="loadDataList"
        :dataSource="tableData"
        :showPagination="false"
      >
        <template #slotAmount="{ row }">
          {{ formatAmount(row.refundAmount) }}
        </template>
        <template #slotError="{ row }">
          <div class="error-text">{{ row.lastError || '--' }}</div>
        </template>
        <template #slotOperation="{ row }">
          <div class="list-op-panel">
            <OpBtn icon="icon-edit" tips="通过" @click="openReview(row, 'approve')" />
            <OpBtn icon="icon-delete" type="danger" tips="驳回" @click="openReview(row, 'reject')" />
          </div>
        </template>
      </Table>
    </div>
  </el-card>
  <el-dialog v-model="dialog.visible" :title="dialog.action === 'approve' ? '通过退款复核' : '驳回退款复核'" width="480px" destroy-on-close>
    <p class="detail-row">退款请求：{{ dialog.row?.refundRequestId }}</p>
    <p class="detail-row">订单：{{ dialog.row?.orderId }} · 明细 {{ dialog.row?.orderItemId }}</p>
    <p class="detail-row">金额：{{ formatAmount(dialog.row?.refundAmount) }}</p>
    <el-form label-position="top" style="margin-top: 16px">
      <el-form-item label="审批说明" required>
        <el-input v-model="dialog.reason" type="textarea" :rows="3" maxlength="200" show-word-limit placeholder="请填写通过或驳回原因" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="dialog.submitting" @click="submitReview">确认</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, getCurrentInstance } from 'vue'

const { proxy } = getCurrentInstance()
const OPERATOR = 'admin'
const reviewKeys = new Map()

const columns = [
  { label: '退款请求', prop: 'refundRequestId', width: 220 },
  { label: '订单号', prop: 'orderId', width: 180 },
  { label: '订单明细', prop: 'orderItemId', width: 180 },
  { label: '用户', prop: 'userId', width: 120 },
  { label: '金额', scopedSlots: 'slotAmount', width: 100 },
  { label: '原阶段', prop: 'reviewOriginStatus', width: 140 },
  { label: '最近错误', scopedSlots: 'slotError' },
  { label: '操作', prop: 'operation', width: 120, scopedSlots: 'slotOperation' },
]

const tableInfoRef = ref()
const tableData = ref({ list: [] })
const dialog = reactive({
  visible: false,
  submitting: false,
  action: 'approve',
  reason: '',
  row: null,
})

const formatAmount = (value) => {
  if (value == null || value === '') return '--'
  const number = Number(value)
  return Number.isFinite(number) ? `¥${number.toFixed(2)}` : String(value)
}

const reviewIdFor = (row, action) => {
  const key = `${row.refundRequestId}:${action}`
  if (!reviewKeys.has(key)) {
    reviewKeys.set(key, crypto.randomUUID())
  }
  return reviewKeys.get(key)
}

const loadDataList = async () => {
  const result = await proxy.Request({
    url: proxy.Api.refundReviewLoadList,
    params: { limit: 100 },
  })
  if (!result) return
  tableData.value = { list: result.data || [] }
}

const openReview = (row, action) => {
  dialog.action = action
  dialog.row = row
  dialog.reason = ''
  dialog.visible = true
}

const submitReview = async () => {
  const reason = dialog.reason.trim()
  if (!reason) {
    proxy.Message.warning('请填写审批说明')
    return
  }
  dialog.submitting = true
  try {
    const row = dialog.row
    const result = await proxy.Request({
      url: dialog.action === 'approve' ? proxy.Api.refundReviewApprove : proxy.Api.refundReviewReject,
      params: {
        refundRequestId: row.refundRequestId,
        reviewId: reviewIdFor(row, dialog.action),
        operator: OPERATOR,
        reason,
      },
    })
    if (!result) return
    reviewKeys.delete(`${row.refundRequestId}:${dialog.action}`)
    proxy.Message.success(dialog.action === 'approve' ? '已通过，退款将继续推进' : '已驳回该退款请求')
    dialog.visible = false
    loadDataList()
  } finally {
    dialog.submitting = false
  }
}
</script>

<style lang="scss" scoped>
.table-panel {
  height: calc(100vh - 135px);

  .error-text {
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.detail-row {
  margin: 0 0 8px;
  color: #4b5b63;
  font-size: 13px;
}
</style>
