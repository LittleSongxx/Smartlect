<template>
  <div class="layout">
    <aside class="left-side">
      <div class="left-side-content">
        <div class="logo">
          <div class="logo-row">
            <BrandMark class="logo-mark" />
            <div class="logo-copy">
              <span class="logo-text">Smartlect</span>
              <span class="logo-sub">智选商城</span>
            </div>
          </div>
        </div>
        <nav class="menu-nav">
          <template v-for="item in visibleMenu" :key="item.path || item.name">
            <div :class="['menu-item', isMenuActive(item) ? 'active' : '']" @click="jump(item)">
              <div :class="['iconfont', `icon-${item.icon}`, 'menu-icon']"></div>
              <div class="menu-name">{{ item.name }}</div>
              <div
                v-if="item.children"
                :class="['iconfont', 'icon-right', 'icon-down', item.opened ? 'icon-right-opened' : 'icon-right-closed']"
              ></div>
            </div>
            <div
              v-if="item.children"
              :class="['submenu-container', item.opened ? 'submenu-opened' : 'submenu-closed']"
            >
              <div
                v-for="sub in item.children"
                :key="sub.path"
                :class="['submenu-item', route.path === sub.path ? 'active' : '']"
                @click="jump(sub)"
              >
                <span class="submenu-dot"></span>
                {{ sub.name }}
              </div>
            </div>
          </template>
        </nav>
      </div>
      <div class="sidebar-glow" aria-hidden="true"></div>
    </aside>

    <div class="right">
      <header class="top">
        <div class="top-main">
          <el-breadcrumb separator="/" class="breadcrumb">
            <el-breadcrumb-item v-for="item in route.meta.itemList" :key="item">
              {{ item }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="top-actions">
          <el-dropdown v-if="scopes.length && !isTrial" trigger="click" @command="changeScope">
            <button type="button" class="action-pill" :disabled="switchingScope">
              <span class="iconfont icon-folder action-pill__icon"></span>
              {{ currentScopeLabel }}
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="scope in scopes"
                  :key="scope.execution_scope_id"
                  :command="scope.execution_scope_id"
                  :disabled="scope.execution_scope_id === session?.actor?.execution_scope_id"
                >
                  {{ scope.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <div class="user-chip">
            <span class="user-avatar">{{ isTrial ? '展' : '管' }}</span>
            <span class="user-name">{{ isTrial ? '作品集展厅' : (principal?.displayName || '管理员') }}</span>
            <button type="button" class="logout-btn" @click="logout">退出</button>
          </div>
        </div>
      </header>
      <p v-if="isTrial" class="trial-banner">作品集展厅：只能查看经营数据，不能改库存、发知识、发券或查看用户隐私。</p>
      <main class="right-body" :class="{ 'is-home': route.path === '/home' }">
        <router-view v-if="sessionReady" v-slot="{ Component }">
          <component :is="Component" :key="scopeKey" v-bind="pageProps" />
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import BrandMark from '@/components/BrandMark.vue'
import { ref, getCurrentInstance, computed, onMounted, watch, provide } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { session, ownerKey, loadSession, aiGet, selectScope, errorText } from '@/api/client'
import { filterTrialMenu, isTrialAdmin, normalizeAdminPrincipal } from '@/utils/adminAccess'

const { proxy } = getCurrentInstance()
const router = useRouter()
const route = useRoute()

// 经营范围切换（自 GrowthShell 迁入）：AI 相关页面按范围隔离状态，切换后整体重挂载。
const scopes = ref([])
const switchingScope = ref(false)
const scopeKey = computed(() => ownerKey(session.value))
const currentScopeLabel = computed(
  () =>
    scopes.value.find((scope) => scope.execution_scope_id === session.value?.actor?.execution_scope_id)?.label ||
    '当前范围',
)
// 经营计划的审批交接（自 GrowthShell 迁入）：经营页点“明确批准授权”把计划带到活动页，
// 活动页批准后回经营页提示，两条路径都要求这两页是同一个 router-view 的兄弟路由。
const approvalPlan = ref(null)
const merchantNotice = ref('')
const reviewGrant = (plan) => {
  approvalPlan.value = plan || null
  merchantNotice.value = ''
  router.push({ name: 'ads' })
}
const grantApproved = () => {
  approvalPlan.value = null
  merchantNotice.value = '稳定授权已保存；请核对计划状态，并通过执行器继续或恢复原回执。'
  router.push({ name: 'merchant' })
}
const closePlan = () => {
  approvalPlan.value = null
  merchantNotice.value = ''
  router.push({ name: 'merchant' })
}
// 只给需要的那一页绑定计划审批的 props/监听：其余页面收到未声明的 attrs 会刷警告。
const pageProps = computed(() => {
  if (route.name === 'ads') {
    return { merchantPlan: approvalPlan.value, onGrantApproved: grantApproved, onClosePlan: closePlan }
  }
  if (route.name === 'merchant') {
    return { initialNotice: merchantNotice.value, onReviewGrant: reviewGrant }
  }
  return {}
})
watch(scopeKey, async () => {
  scopes.value = []
  approvalPlan.value = null
  merchantNotice.value = ''
  if (session.value?.actor?.subject_type !== 'merchant') return
  try {
    scopes.value = (await aiGet('/scopes')).items
  } catch {
    // 范围列表加载失败不阻塞管理台；AI 页面自身操作会给出明确报错
  }
})
const changeScope = async (executionScopeId) => {
  if (switchingScope.value || executionScopeId === session.value?.actor?.execution_scope_id) return
  switchingScope.value = true
  try {
    await selectScope(executionScopeId)
    proxy.Message.success('经营范围已切换')
  } catch (reason) {
    proxy.Message.error(errorText(reason))
  } finally {
    switchingScope.value = false
  }
}
// 页面 key 取自会话里的 ownerKey；会话解析前它是空串，解析后才变成真实 id。若直接挂载
// 子路由，冷启动会先按空 key 挂一次、再按真实 key 重挂一次，每个页面的首屏请求都发两遍。
const sessionReady = ref(false)
onMounted(async () => {
  try {
    const me = await proxy.Request({ url: proxy.Api.adminMe, method: 'get', showLoading: false })
    if (me?.data) principal.value = normalizeAdminPrincipal(me.data)
  } catch {
    principal.value = null
  }
  try {
    await loadSession()
  } catch {
    // 未登录 assistant 或非商家身份时，范围切换入口保持隐藏
  } finally {
    sessionReady.value = true
  }
})


const isMenuActive = (item) => {
  if (item.path && route.path === item.path) return true
  if (item.children) {
    return item.children.some((sub) => route.path === sub.path)
  }
  return false
}

// 菜单只列"演示故事需要"的页面。分类/属性、收货地址、发货信息、敏感词、签到/会员礼券、
// 统计明细、MQ 补偿、运营工具、图片违规复核都仍在 router 里（可直接访问、随时恢复），
// 只是不再占菜单位：它们或与看板/Grafana 同源，或由种子脚本与用户端承载，属于遗留电商脚手架。
const principal = ref(null)
const isTrial = computed(() => isTrialAdmin(principal.value))
provide('isTrialAdmin', isTrial)
const menuList = ref([
  {
    name: '首页',
    icon: 'home',
    path: '/home',
  },
  {
    name: '商品',
    icon: 'product',
    opened: true,
    children: [
      { name: '商品管理', path: '/product' },
      { name: '分类管理', path: '/product/category' },
      { name: '商品属性', path: '/product/ProductProperty' },
    ],
  },
  {
    name: '订单',
    icon: 'order',
    opened: true,
    children: [
      { name: '订单管理', path: '/order/orderList' },
      { name: '订单评论', path: '/order/comment' },
      { name: '举报管理', path: '/order/report' },
      { name: '退款复核', path: '/order/refundReview' },
    ],
  },
  {
    name: '用户管理',
    icon: 'user',
    opened: true,
    children: [
      { name: '用户列表', path: '/user/userList' },
      { name: '收货地址', path: '/user/address' },
    ],
  },
  {
    name: '营销',
    icon: 'product',
    opened: true,
    children: [
      { name: '优惠券管理', path: '/discountCoupon' },
      { name: '签到发券', path: '/marketing/signReward' },
      { name: '会员升级礼券', path: '/marketing/memberLevelReward' },
    ],
  },
  {
    name: '经营',
    icon: 'setting',
    opened: true,
    children: [
      { name: '经营助手', path: '/merchant' },
      { name: '活动与授权', path: '/ads' },
      { name: '知识库', path: '/knowledge' },
      { name: '人工客服', path: '/support' },
      { name: '评价分析', path: '/reviewAnalysis' },
      { name: '增长报告', path: '/growthReport' },
    ],
  },
  {
    name: '设置',
    icon: 'setting',
    opened: true,
    children: [
      { name: '发货地址', path: '/setting/logistics' },
      { name: '敏感词', path: '/setting/sensitiveWord' },
      { name: '图片审核', path: '/setting/imageModeration' },
    ],
  },
  {
    name: 'AI 资产',
    icon: 'robot',
    opened: true,
    children: [
      { name: '模型配置', path: '/ai/models' },
      { name: '提示词与技能', path: '/ai/prompts' },
      { name: '知识索引', path: '/ai/knowledge-index' },
      { name: '运行浏览器', path: '/ai/runs' },
      { name: '工具调试台', path: '/ai/tools' },
    ],
  },
])

const visibleMenu = computed(() => (isTrial.value ? filterTrialMenu(menuList.value) : menuList.value))

const jump = (item) => {
  if (item.children) {
    item.opened = !item.opened
    return
  }
  router.push(item.path)
}

const logout = () => {
  proxy.Confirm({
    message: '确定要退出吗?',
    okfun: async () => {
      let result = await proxy.Request({
        url: proxy.Api.logout,
      })
      if (!result) {
        return
      }
      router.push('/login')
    },
  })
}
</script>

<style lang="scss" scoped>
.layout {
  display: flex;
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
  background: transparent;

  .left-side {
    position: relative;
    flex-shrink: 0;
    width: 220px;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--sidebar-bg);
    border-right: 1px solid var(--border);

    .sidebar-glow {
      display: none;
    }

    .left-side-content {
      position: relative;
      z-index: 1;
      height: 100%;
      padding-bottom: 20px;
      overflow-y: auto;
      overscroll-behavior: contain;

      .logo {
        padding: 18px 16px 16px;
        border-bottom: 1px solid var(--border-soft);
        margin-bottom: 8px;

        .logo-row {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .logo-mark {
          width: 30px;
          height: 34px;
          flex-shrink: 0;
        }

        .logo-copy {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .logo-text {
          font-size: 18px;
          font-weight: 600;
          letter-spacing: 0;
          color: var(--text);
        }

        .logo-sub {
          font-size: 11px;
          font-weight: 500;
          color: var(--sidebar-text-muted);
          letter-spacing: 0;
        }
      }

      .menu-item {
        display: flex;
        align-items: center;
        height: 50px;
        margin: 0;
        padding: 0 16px;
        font-size: 14px;
        color: var(--sidebar-text);
        cursor: pointer;
        transition: background 0.2s, color 0.2s;

        &:hover {
          background: var(--sidebar-hover);
          color: var(--sidebar-text-active);
        }

        &.active {
          background: var(--sidebar-active-bg);
          color: var(--sidebar-text-active);
          font-weight: 600;
        }

        .menu-icon {
          font-size: 16px;
          opacity: 0.9;
        }

        .menu-name {
          flex: 1;
          margin-left: 10px;
          min-width: 0;
        }

        .icon-right {
          font-size: 11px;
          opacity: 0.65;
          transition: transform 0.25s ease;
        }

        .icon-right-opened {
          transform: rotate(180deg);
        }
      }

      .submenu-item {
        display: flex;
        align-items: center;
        gap: 8px;
        height: 44px;
        margin: 0;
        padding: 0 16px 0 50px;
        font-size: 13px;
        color: var(--sidebar-text-muted);
        cursor: pointer;
        transition: background 0.2s, color 0.2s;

        .submenu-dot {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: var(--border);
          flex-shrink: 0;
        }

        &:hover {
          background: var(--sidebar-hover);
          color: var(--sidebar-text);
        }

        &.active {
          background: var(--sidebar-active-bg);
          color: var(--sidebar-text-active);
          font-weight: 500;

          .submenu-dot {
            background: var(--accent);
          }
        }
      }

      .submenu-container {
        transition: max-height 0.28s ease, opacity 0.22s ease;
      }

      .submenu-opened {
        max-height: 520px;
        opacity: 1;
      }

      .submenu-closed {
        max-height: 0;
        opacity: 0;
        overflow: hidden;
      }
    }
  }

  .right {
    flex: 1;
    width: 0;
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;

    .top {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 60px;
      padding: 10px 24px;
      background: var(--surface);
      border-bottom: 1px solid var(--header-border);
      box-shadow: var(--shadow-header);

      .top-main {
        min-width: 0;

        .breadcrumb {
          :deep(.el-breadcrumb) {
            line-height: 1.4;
            font-size: 12px;
          }

          :deep(.el-breadcrumb__inner) {
            color: var(--text3);
            font-weight: 400;
          }

          :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
            color: var(--text2);
          }
        }
      }

      .top-actions {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-shrink: 0;
      }

      .action-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 36px;
        padding: 0 14px;
        border: 1px solid var(--header-border);
        border-radius: 999px;
        background: var(--surface);
        color: var(--text2);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: border-color 0.2s, color 0.2s, box-shadow 0.2s;

        .action-pill__icon {
          font-size: 14px;
        }

        &:hover {
          color: var(--text);
          border-color: rgba(23, 32, 42, 0.14);
          box-shadow: var(--shadow-sm);
        }

        &.action-pill--ghost {
          background: transparent;
        }
      }

      .user-chip {
        display: flex;
        align-items: center;
        gap: 8px;
        height: 36px;
        padding: 0 6px 0 4px;
        border: 1px solid var(--header-border);
        border-radius: 999px;
        background: var(--surface);

        .user-avatar {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: var(--primary);
          color: #fff;
          font-size: 12px;
          font-weight: 600;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .user-name {
          font-size: 13px;
          color: var(--text2);
          padding-right: 4px;
        }

        .logout-btn {
          height: 28px;
          padding: 0 12px;
          border: none;
          border-radius: 999px;
          background: var(--primary-soft);
          color: var(--primary);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.2s;

          &:hover {
            background: var(--accent-soft);
            color: var(--accent-hover);
          }
        }
      }
    }

    .trial-banner {
      margin: 0 20px 0;
      padding: 8px 12px;
      border-radius: 8px;
      background: var(--surface-soft);
      color: var(--text-2);
      font-size: 13px;
    }

    .right-body {
      flex: 1;
      margin: 16px 16px 16px 0;
      padding: 20px 22px;
      border-radius: var(--card-radius);
      background: var(--surface);
      border: 1px solid var(--header-border);
      box-shadow: var(--shadow-card);
      overflow: auto;
      min-height: 0;
      min-width: 0;
      overscroll-behavior: contain;

      &.is-home {
        background: transparent;
        border-color: transparent;
        box-shadow: none;
        margin: 14px 20px 16px;
        padding: 0;
      }
    }
  }
}
</style>
