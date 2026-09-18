import { createRouter, createWebHashHistory } from 'vue-router'

// 管理端只保留桌面形态：手机端管理台（/m/**）已下线——它是桌面页的 1:1 复刻、零测试，
// 演示故事也不需要。旧书签命中的 /m/** 一律回首页，不做 404。
const LEGACY_MOBILE_PREFIX = '/m'

export const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/account/Account.vue')
  },
  {
    path: '/',
    name: 'Layout',
    redirect: '/login',
    component: () => import('@/views/Layout.vue'),
    children: [
      { path: '/home', name: 'home', component: () => import('@/views/home/Home.vue'), meta: { itemList: ['首页'] } },
      { path: '/product/category', name: 'category', component: () => import('@/views/product/Category.vue'), meta: { itemList: ['商品', '分类管理'] } },
      { path: '/product/ProductProperty', name: 'productProperty', component: () => import('@/views/product/ProductProperty.vue'), meta: { itemList: ['商品', '商品属性'] } },
      { path: '/product/addProduct', name: 'addProduct', component: () => import('@/views/product/edit/ProductEdit.vue'), meta: { itemList: ['商品', '商品管理'] } },
      { path: '/product/updateProduct/:productId', name: 'updateProduct', component: () => import('@/views/product/edit/ProductEdit.vue'), meta: { itemList: ['商品', '商品管理'] } },
      { path: '/product', name: 'product', component: () => import('@/views/product/ProductList.vue'), meta: { itemList: ['商品', '商品管理'] } },
      { path: '/order/orderList', name: '订单管理', component: () => import('@/views/order/OrderList.vue'), meta: { itemList: ['订单', '订单管理'] } },
      { path: '/order/comment', name: '订单评论', component: () => import('@/views/order/OrderCommentList.vue'), meta: { itemList: ['订单', '订单评论'] } },
      { path: '/order/report', name: '举报管理', component: () => import('@/views/order/CommentReportList.vue'), meta: { itemList: ['订单', '举报管理'] } },
      { path: '/order/refundReview', name: '退款复核', component: () => import('@/views/order/RefundReviewList.vue'), meta: { itemList: ['订单', '退款复核'] } },
      { path: '/setting/imageModeration', name: '图片审核', component: () => import('@/views/setting/ImageModerationList.vue'), meta: { itemList: ['订单', '图片违规复核'] } },
      { path: '/user/userList', name: '用户管理', component: () => import('@/views/user/UserList.vue'), meta: { itemList: ['用户管理', '用户列表'] } },
      { path: '/user/address', name: '收货地址', component: () => import('@/views/user/UserAddressList.vue'), meta: { itemList: ['用户管理', '收货地址'] } },
      { path: '/setting/logistics', name: '发货地址', component: () => import('@/views/setting/Logistics.vue'), meta: { itemList: ['设置', '发货地址'] } },
      { path: '/setting/sensitiveWord', name: '敏感词管理', component: () => import('@/views/setting/SensitiveWord.vue'), meta: { itemList: ['设置', '敏感词管理'] } },
      { path: '/discountCoupon', name: '优惠券管理', component: () => import('@/views/discount/DiscountCouponList.vue'), meta: { itemList: ['营销', '优惠券管理'] } },
      { path: '/marketing/signReward', name: '签到发券配置', component: () => import('@/views/marketing/SignRewardConfig.vue'), meta: { itemList: ['营销', '签到发券配置'] } },
      { path: '/marketing/memberLevelReward', name: '会员升级礼券', component: () => import('@/views/marketing/MemberLevelRewardConfig.vue'), meta: { itemList: ['营销', '会员升级礼券'] } },
      { path: '/data/tools', name: '运营工具', component: () => import('@/views/data/OperateTools.vue'), meta: { itemList: ['数据中心', '运营工具'] } },
      { path: '/data/statistics', name: '统计明细', component: () => import('@/views/data/StatisticsList.vue'), meta: { itemList: ['数据中心', '统计明细'] } },
      { path: '/data/mqCompensationLog', name: 'MQ补偿审查', component: () => import('@/views/data/MqCompensationLogList.vue'), meta: { itemList: ['数据中心', 'MQ补偿审查'] } },
      { path: '/merchant', name: 'merchant', component: () => import('@/views/common/DisabledFeatureView.vue'), meta: { itemList: ['经营', '经营助手（已停用）'], disabledTitle: '经营助手', disabledDetail: '商家规划 Agent 已停用，不再生成或执行经营计划。知识库与人工客服不受影响。' } },
      { path: '/ads', name: 'ads', component: () => import('@/views/common/DisabledFeatureView.vue'), meta: { itemList: ['经营', '活动与授权（已停用）'], disabledTitle: '活动与授权', disabledDetail: '付费广告投放已停用。用户端首页滚动位改为确定性推荐，不再展示或计费广告。' } },
      { path: '/knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue'), meta: { itemList: ['经营', '知识库'] } },
      { path: '/support', name: 'support', component: () => import('@/views/SupportView.vue'), meta: { itemList: ['经营', '人工客服'] } },
      { path: '/reviewAnalysis', name: 'reviewAnalysis', component: () => import('@/views/common/DisabledFeatureView.vue'), meta: { itemList: ['经营', '评价分析（已停用）'], disabledTitle: '评价分析', disabledDetail: '评价分析已停用，不再生成统计洞察。' } },
      { path: '/growthReport', name: 'growthReport', component: () => import('@/views/common/DisabledFeatureView.vue'), meta: { itemList: ['经营', '增长报告（已停用）'], disabledTitle: '增长报告', disabledDetail: '增长报告已停用，不再生成经营建议。' } },
      { path: '/ai/models', name: 'aiModels', component: () => import('@/views/ai/ModelConfigView.vue'), meta: { itemList: ['AI 资产', '模型配置'] } },
      { path: '/ai/prompts', name: 'aiPrompts', component: () => import('@/views/ai/PromptSkillView.vue'), meta: { itemList: ['AI 资产', '提示词与技能'] } },
      { path: '/ai/knowledge-index', name: 'aiKnowledgeIndex', component: () => import('@/views/ai/KnowledgeIndexView.vue'), meta: { itemList: ['AI 资产', '知识索引'] } },
      { path: '/ai/runs', name: 'aiRuns', component: () => import('@/views/ai/AgentRunsView.vue'), meta: { itemList: ['AI 资产', '运行浏览器'] } },
      { path: '/ai/tools', name: 'aiTools', component: () => import('@/views/ai/ToolDebugView.vue'), meta: { itemList: ['AI 资产', '工具调试台'] } }
    ]
  },
  // 未知路径落回首页：此前会渲染空白内容区（例如手输错的 #/order）
  { path: '/:pathMatch(.*)*', redirect: { path: '/home' } }
]

export function createAdminRouter(history) {
  const router = createRouter({
    history: history || createWebHashHistory(),
    routes
  })
  if (!history) {
    router.beforeEach((to) => {
      if (to.path === '/login') return true
      if (to.path === LEGACY_MOBILE_PREFIX || to.path.startsWith(LEGACY_MOBILE_PREFIX + '/')) {
        return { path: '/home', query: to.query }
      }
      return true
    })
  }
  return router
}

const router = createAdminRouter()
export default router
