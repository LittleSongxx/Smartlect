<template>
  <div class="m-simple">
    <div class="m-search glass-card glass-strong">
      <button type="button" class="refresh-btn" :disabled="loading" @click="loadList">刷新待复核</button>
    </div>

    <div v-if="list.length" class="m-list">
      <div v-for="row in list" :key="row.refundRequestId" class="glass-card rpt-card">
        <div class="rpt-head">
          <span class="rpt-reason">{{ row.orderId || row.refundRequestId }}</span>
          <span class="rpt-status pending">待复核</span>
        </div>
        <p class="rpt-order">明细：{{ row.orderItemId || '--' }}</p>
        <p class="rpt-detail">金额：{{ formatAmount(row.refundAmount) }} · 原阶段 {{ row.reviewOriginStatus || '--' }}</p>
        <p v-if="row.lastError" class="rpt-snapshot">{{ row.lastError }}</p>
        <div class="rpt-ops">
          <button type="button" class="op-btn primary" @click="openReview(row, 'approve')">通过</button>
          <button type="button" class="op-btn danger" @click="openReview(row, 'reject')">驳回</button>
        </div>
      </div>
    </div>
    <p v-else-if="!loading" class="m-empty-tip">暂无待复核退款</p>
    <p v-else class="m-empty-tip">加载中…</p>
  </div>
</template>

<script setup>
import { ref, getCurrentInstance } from 'vue'

const { proxy } = getCurrentInstance()
const OPERATOR = 'admin'
const reviewKeys = new Map()
const list = ref([])
const loading = ref(false)

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

const loadList = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const result = await proxy.Request({
      url: proxy.Api.refundReviewLoadList,
      params: { limit: 100 },
      showLoading: false,
    })
    if (!result) return
    list.value = result.data || []
  } finally {
    loading.value = false
  }
}

const openReview = async (row, action) => {
  const reason = window.prompt(action === 'approve' ? '通过后退款将继续推进，请填写原因' : '驳回后该退款将终止，请填写原因')
  if (reason == null) return
  if (!reason.trim()) {
    proxy.Message.warning('请填写审批说明')
    return
  }
  const result = await proxy.Request({
    url: action === 'approve' ? proxy.Api.refundReviewApprove : proxy.Api.refundReviewReject,
    params: {
      refundRequestId: row.refundRequestId,
      reviewId: reviewIdFor(row, action),
      operator: OPERATOR,
      reason: reason.trim(),
    },
    showLoading: true,
  })
  if (!result) return
  reviewKeys.delete(`${row.refundRequestId}:${action}`)
  proxy.Message.success(action === 'approve' ? '已通过' : '已驳回')
  loadList()
}

loadList()
</script>

<style lang="scss" scoped>
.m-simple {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.refresh-btn {
  width: 100%;
  height: 40px;
  border: 0;
  border-radius: 8px;
  background: var(--m-ink);
  color: #fff;
  font-size: 14px;
}

.m-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rpt-card {
  padding: 12px 14px;

  .rpt-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .rpt-reason {
    font-size: 14px;
    font-weight: 600;
    color: var(--m-ink);
  }

  .rpt-status {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 8px;
    font-weight: 500;

    &.pending {
      background: rgba(255, 149, 0, 0.12);
      color: #b87000;
    }
  }

  .rpt-order,
  .rpt-detail {
    margin: 8px 0 4px;
    font-size: 12px;
    color: var(--m-ink-3);
  }

  .rpt-snapshot {
    margin: 6px 0;
    padding: 6px 10px;
    border-radius: 8px;
    background: rgba(120, 120, 128, 0.06);
    font-size: 12px;
    color: var(--m-ink-2);
    line-height: 1.45;
  }

  .rpt-ops {
    display: flex;
    gap: 8px;
    margin-top: 10px;

    .op-btn {
      flex: 1;
      height: 32px;
      border: 1px solid rgba(120, 120, 128, 0.24);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.5);
      color: var(--m-ink-2);
      font-size: 12px;
      cursor: pointer;

      &.primary {
        color: var(--m-blue);
        border-color: rgba(0, 113, 227, 0.3);
      }

      &.danger {
        color: var(--m-danger);
        border-color: rgba(255, 59, 48, 0.3);
      }
    }
  }
}

.m-empty-tip {
  margin: 24px 0;
  text-align: center;
  font-size: 14px;
  color: var(--m-ink-3);
}
</style>
