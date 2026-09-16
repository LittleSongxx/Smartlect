<template>
  <div class="m-more">
    <section v-for="group in groups" :key="group.title" class="glass-card m-group">
      <h3 class="m-group-title">{{ group.title }}</h3>
      <div class="m-grid">
        <button
          v-for="item in group.items"
          :key="item.label"
          type="button"
          class="m-entry"
          @click="go(item)"
        >
          <span class="iconfont entry-icon" :class="`icon-${item.icon}`"></span>
          <span class="entry-label">{{ item.label }}</span>
        </button>
      </div>
    </section>

    <section class="glass-card m-account">
      <div class="acc-row">
        <span class="iconfont icon-account acc-icon"></span>
        <div class="acc-info">
          <span class="acc-name">管理员</span>
          <span class="acc-sub">智选商城运营后台 · 移动端</span>
        </div>
      </div>
      <button type="button" class="acc-logout" @click="logout">退出登录</button>
    </section>
  </div>
</template>

<script setup>
import { getCurrentInstance } from 'vue'
import { useRouter } from 'vue-router'

const { proxy } = getCurrentInstance()
const router = useRouter()

const groups = [
  {
    title: '订单与评价',
    items: [
      { label: '评价管理', icon: 'commend', path: '/m/order/comment' },
      { label: '举报管理', icon: 'commend', path: '/m/order/report' },
      { label: '退款复核', icon: 'order-count', path: '/m/order/refundReview' },
      { label: '图片违规复核', icon: 'search', path: '/m/more/imageModeration' }
    ]
  },
  {
    title: '营销',
    items: [
      { label: '优惠券', icon: 'cart', path: '/m/more/coupon' },
      { label: '签到发券', icon: 'commend', path: '/m/more/signReward' },
      { label: '升级礼券', icon: 'account', path: '/m/more/memberLevelReward' }
    ]
  },
    {
      title: '数据',
      items: [
        { label: '统计明细', icon: 'order-count', path: '/m/more/statistics' },
        { label: 'MQ补偿日志', icon: 'setting', path: '/m/more/mqLog' },
        { label: '收货地址', icon: 'folder', path: '/m/more/address' }
      ]
    },
  {
    title: '系统设置',
    items: [
      { label: '发货信息', icon: 'setting', path: '/m/more/logistics' },
      { label: '敏感词', icon: 'search', path: '/m/more/sensitiveWord' },
      { label: '经营助手', icon: 'setting', path: '/m/more/merchant' },
      { label: '活动与授权', icon: 'setting', path: '/m/more/ads' },
      { label: '知识库', icon: 'folder', path: '/m/more/knowledge' },
      { label: '人工客服', icon: 'robot', path: '/m/more/support' },
      { label: '评价分析', icon: 'commend', path: '/m/more/reviewAnalysis' },
      { label: '增长报告', icon: 'rise', path: '/m/more/growthReport' },
      { label: '分类管理', icon: 'product', path: '/m/more/category' },
      { label: '商品属性', icon: 'stock', path: '/m/more/productProperty' },
      { label: '运营工具', icon: 'setting', path: '/m/more/tools' }
    ]
  },
  {
    title: 'AI 资产',
    items: [
      { label: '模型配置', icon: 'setting', path: '/m/more/aiModels' },
      { label: '提示词与技能', icon: 'folder', path: '/m/more/aiPrompts' },
      { label: '知识索引', icon: 'search', path: '/m/more/aiKnowledgeIndex' },
      { label: '运行浏览器', icon: 'robot', path: '/m/more/aiRuns' },
      { label: '工具调试台', icon: 'edit', path: '/m/more/aiTools' }
    ]
  }
]

const go = (item) => {
  if (item.path) {
    router.push(item.path)
  }
}

const logout = () => {
  proxy.Confirm({
    message: '确定要退出登录吗?',
    okfun: async () => {
      await proxy.Request({ url: proxy.Api.logout })
      router.push('/login')
    }
  })
}
</script>

<style lang="scss" scoped>
.m-more {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.m-group {
  padding: 14px;
}

.m-group-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--m-ink);
}

.m-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.m-entry {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 10px 4px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.45);
  cursor: pointer;
  transition: transform 0.15s, background 0.2s;

  &:active {
    transform: scale(0.93);
    background: var(--m-gold-soft);
  }

  .entry-icon {
    font-size: 22px;
    color: var(--m-ink);
  }

  .entry-label {
    font-size: 11px;
    color: var(--m-ink-2);
    text-align: center;
    line-height: 1.2;
  }
}

.m-account {
  padding: 16px;

  .acc-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;

    .acc-icon {
      width: 46px;
      height: 46px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--m-gold-soft);
      color: var(--m-ink);
      font-size: 24px;
    }

    .acc-info {
      display: flex;
      flex-direction: column;
    }

    .acc-name {
      font-size: 15px;
      font-weight: 600;
      color: var(--m-ink);
    }

    .acc-sub {
      font-size: 12px;
      color: var(--m-ink-3);
    }
  }

  .acc-logout {
    width: 100%;
    height: 42px;
    border-radius: 8px;
    font-size: 14px;
    cursor: pointer;
    transition: transform 0.15s;

    &:active {
      transform: scale(0.98);
    }
  }

  .acc-logout {
    border: 1px solid rgba(255, 59, 48, 0.28);
    background: rgba(255, 59, 48, 0.08);
    color: var(--m-danger);
  }
}
</style>
