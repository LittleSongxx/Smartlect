<template>
  <div class="account-page" :class="{ ignore: isDesktop, 'user-center-layout': isDesktop }">
    <PcUserSidebar v-if="isDesktop" />
    <div :class="isDesktop ? 'user-center-content account-dashboard' : 'account-body'">
    <div v-if="!isDesktop" class="smartlect-user-top">
      <div class="smartlect-user-head">
        <h1 class="smartlect-user-title">个人中心</h1>
        <button
          type="button"
          class="smartlect-user-setting"
          aria-label="设置"
          @click="router.push('/account/manage')"
        >
          <el-icon :size="20"><Setting /></el-icon>
        </button>
      </div>

    <section class="profile-card">
      <button type="button" class="profile-main" @click="goProfile">
        <UserAvatar :avatar="user?.avatar" :size="56" />
        <div class="profile-info">
          <div class="nick-row">
            <h2 class="nick">{{ user?.nickName || '智选商城用户' }}</h2>
          </div>
          <p class="account">{{ user?.email || '完善资料享更多权益' }}</p>
        </div>
        <el-icon class="profile-arrow"><ArrowRight /></el-icon>
      </button>
    </section>

    <section class="wallet-strip-top">
      <div class="wallet-item-top" @click="router.push('/orders')">
        <span class="wallet-value-top">{{ totalOrderCount }}</span>
        <span class="wallet-label-top">订单</span>
      </div>
      <div class="wallet-item-top" @click="router.push('/my-coupons')">
        <span class="wallet-value-top">{{ couponCount }}</span>
        <span class="wallet-label-top">优惠券</span>
      </div>
    </section>
    </div>

    <section class="order-card card">
      <div class="card-head">
        <h3>我的订单</h3>
        <RouterLink to="/orders" class="link-more">全部订单</RouterLink>
      </div>
      <div class="order-grid">
        <button
          v-for="item in orderTabs"
          :key="item.code"
          type="button"
          class="order-tab"
          @click="goOrders(item)"
        >
          <el-badge :value="countMap[item.code] || 0" :hidden="!countMap[item.code]" :max="99">
            <el-icon :size="26"><component :is="item.icon" /></el-icon>
          </el-badge>
          <span>{{ item.name }}</span>
        </button>
      </div>
    </section>

    <section class="menu-card card">
      <h3 class="menu-title">常用服务</h3>
      <div class="menu-grid">
        <template v-for="m in menus" :key="m.path">
          <button v-if="m.openAgent" type="button" class="menu-item" @click="openAgent()">
            <el-icon :size="24" class="menu-icon"><component :is="m.icon" /></el-icon>
            <span class="menu-label">{{ m.label }}</span>
          </button>
          <RouterLink v-else :to="m.path" class="menu-item">
            <el-icon :size="24" class="menu-icon"><component :is="m.icon" /></el-icon>
            <span class="menu-label">{{ m.label }}</span>
          </RouterLink>
        </template>
      </div>
    </section>

    <section class="discover-card card">
      <div class="discover-tabs toolbar-row"><span class="discover-tab active">推荐</span></div>

      <div class="discover-body">
        <div v-if="recommendProducts.length" :class="isDesktop ? 'pc-recommend-grid' : 'recommend-grid'">
          <template v-if="isDesktop">
            <PcProductTile
              v-for="item in recommendProducts"
              :key="`${item.product.productId}-${item.displayIndex}`"
              :product="item.product"
              @click="goProduct"
            />
          </template>
          <template v-else>
            <ProductCard
              v-for="item in recommendProducts"
              :key="`${item.product.productId}-${item.displayIndex}`"
              :product="item.product"
              compact
              @click="goProduct"
            />
          </template>
        </div>
        <el-empty v-else-if="!discoverLoading" description="暂无推荐商品" :image-size="72" />
        <p v-if="discoverLoading" class="discover-tip">加载中…</p>
        <div ref="recommendSentinel" class="feed-sentinel">
          <span v-if="discoverLoading" class="feed-tip">加载中…</span>
          <span v-else-if="recommendProducts.length >= MAX_RECOMMEND" class="feed-tip">已展示全部推荐商品</span>
          <span v-else-if="recommendSourceProducts.length === 0 && !discoverLoading" class="feed-tip">暂无推荐商品</span>
        </div>
      </div>

    </section>

    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import PcUserSidebar from '@/components/layout/PcUserSidebar.vue';
import { useDevice } from '@/composables/useDevice';
import { useOpenAgent } from '@/composables/useOpenAgent';
import {
  ArrowRight,
  Bell,
  ChatDotRound,
  Location,
  Medal,
  Present,
  Setting,
  Ticket,
  Wallet,
  Box,
  Van,
  Star,
  User,
  Tickets
} from '@element-plus/icons-vue';
import UserAvatar from '@/components/common/UserAvatar.vue';
import ProductCard from '@/components/business/ProductCard.vue';
import PcProductTile from '@/components/pc/PcProductTile.vue';
import { resolveImageUrl, splitImagePaths } from '@/utils/image';
import { accountApi, couponApi, orderApi, productApi } from '@/api/modules';
import { useAuthStore } from '@/stores/auth';
import { filterStorefrontProducts } from '@/utils/product';
import { usePageRefresh } from '@/composables/pullRefresh';
import { ElMessageBox } from 'element-plus';

const router = useRouter();
const { isDesktop } = useDevice();
const { openAgent } = useOpenAgent();
const authStore = useAuthStore();
const user = ref<Record<string, any>>({});
const countMap = reactive<Record<string, number>>({});
const couponCount = ref(0);

const discoverLoading = ref(false);
const recommendProducts = ref<any[]>([]);
const recommendSourceProducts = ref<any[]>([]);
const recommendDisplayCount = ref(0);
const MAX_RECOMMEND = 90;
const recommendSentinel = ref<HTMLElement | null>(null);
let recommendObserver: IntersectionObserver | null = null;

const goProfile = () => router.push('/account/settings');
const goProduct = (p: any) => {
  if (p?.productId) router.push(`/product/${p.productId}`);
};

const showAllProducts = (row: Record<string, any>) => {
  const items = row.orderItems || []
  let html = '<div style="max-height:400px;overflow-y:auto;">'
  items.forEach((item: Record<string, any>, idx: number) => {
    const cover = item.cover ? `<img src="${resolveImageUrl(item.cover)}" style="width:60px;height:60px;object-fit:cover;border-radius:6px;flex-shrink:0;" />` : ''
    html += `<div style="display:flex;gap:12px;padding:10px 0;${idx > 0 ? 'border-top:1px solid #eee;' : ''}">
      ${cover}
      <div style="flex:1;min-width:0;">
        <div style="font-size:14px;font-weight:500;margin-bottom:4px;color:#333029;">${item.productName || ''}</div>
        <div style="font-size:12px;color:#6c6560;">${item.propertyInfo || ''}</div>
        <div style="font-size:12px;color:#6c6560;margin-top:2px;">￥${item.itemAmount || 0} × ${item.buyCount || 0}</div>
      </div>
    </div>`
  })
  html += '</div>'
  try {
    ElMessageBox.alert(html, '该订单商品', {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '关闭',
      showCancelButton: false,
      closeOnClickModal: true,
    })
  } catch (e) {
    console.error(e)
  }
}

const orderTabs = [
  { code: 'pendingPayment', name: '待付款', status: '0', icon: Wallet },
  { code: 'pendingShipment', name: '待发货', status: '1', icon: Box },
  { code: 'pendingReceipt', name: '待收货', status: '2', icon: Van },
  { code: 'afterSale', name: '售后', status: 'all', icon: ChatDotRound }
];

const menus: Array<{ label: string; path: string; icon: typeof Medal; openAgent?: boolean }> = [
  { label: '支付记录', path: '/pay-records', icon: Wallet },
  { label: '收货地址', path: '/address', icon: Location },
  { label: '优惠券', path: '/my-coupons', icon: Ticket },
  { label: '智能客服', path: '/ai-assistant', icon: ChatDotRound, openAgent: true },
  { label: '购物偏好', path: '/shopping-profile', icon: User },
  { label: '我的工单', path: '/assistant', icon: Tickets, openAgent: true }
];

const totalOrderCount = computed(() => countMap['completed'] || 0);

const load = async () => {
  user.value = (await accountApi.getUserInfo()) || authStore.userInfo || {};
  authStore.userInfo = { ...authStore.userInfo, ...user.value };
  const counts = await orderApi.getOrderCountInfo();
  if (Array.isArray(counts)) {
    counts.forEach((item: { code: string; count: number }) => {
      countMap[item.code] = item.count ?? 0;
    });
  }
  if (authStore.isLoggedIn) {
    try {
      const couponRes = await couponApi.loadUserCoupon({ pageNo: 1, status: 0 });
      couponCount.value = couponRes?.list?.length ?? 0;
    } catch {
      couponCount.value = 0;
    }
  }
};

const loadRecommend = async () => {
  discoverLoading.value = true;
  try {
    const commend = await productApi.loadCommendProduct();
    const list = Array.isArray(commend) ? commend : commend?.list;
    recommendSourceProducts.value = filterStorefrontProducts(list);

    const initialCount = isDesktop.value ? 12 : 8;
    recommendDisplayCount.value = Math.min(initialCount, MAX_RECOMMEND);
    updateRecommendDisplay();
  } finally {
    discoverLoading.value = false;
  }
};

const updateRecommendDisplay = () => {
  if (recommendSourceProducts.value.length === 0) {
    recommendProducts.value = [];
    return;
  }

  const result: { product: any; displayIndex: number }[] = [];
  const sourceLength = recommendSourceProducts.value.length;

  for (let i = 0; i < recommendDisplayCount.value; i++) {
    const sourceIndex = i % sourceLength;
    result.push({ product: recommendSourceProducts.value[sourceIndex], displayIndex: i });
  }

  recommendProducts.value = result;
};

const loadMoreRecommend = () => {
  if (recommendDisplayCount.value >= MAX_RECOMMEND) return;

  const increment = isDesktop.value ? 12 : 8;
  recommendDisplayCount.value = Math.min(recommendDisplayCount.value + increment, MAX_RECOMMEND);
  updateRecommendDisplay();
};

const setupRecommendObserver = () => {
  if (recommendObserver) return;

  recommendObserver = new IntersectionObserver(
    (entries) => {
      const entry = entries[0];
      if (entry.isIntersecting && !discoverLoading.value && recommendDisplayCount.value < MAX_RECOMMEND) {
        loadMoreRecommend();
      }
    },
    {
      rootMargin: '200px',
      threshold: 0.1
    }
  );

  if (recommendSentinel.value) {
    recommendObserver.observe(recommendSentinel.value);
  }
};

const cleanupRecommendObserver = () => {
  if (recommendObserver) {
    recommendObserver.disconnect();
    recommendObserver = null;
  }
};

const goOrders = (item: { code?: string; status?: string }) => {
  if (item.code === 'afterSale' || item.status === 'all') {
    router.push('/after-sale');
    return;
  }
  router.push({ path: '/orders', query: { status: item.status } });
};

const refreshPage = async () => {
  await load();
  await loadRecommend();
};

onMounted(async () => {
  await load();
  await loadRecommend();

  setTimeout(() => {
    setupRecommendObserver();
  }, 100);
});

onUnmounted(() => {
  cleanupRecommendObserver();
});
usePageRefresh(refreshPage);
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.account-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 (-$app-page-gutter);
  padding: 0 0 16px;
  background: linear-gradient(180deg, #FFFFFF 0%, $color-bg 120px);

  &.user-center-layout {
    flex-direction: row;
    align-items: flex-start;
    margin: 0;
    padding: 0;
    gap: 16px;
    background: transparent;
  }

  :deep(.member-summary--pc) {
    margin: 0 0 12px;
  }
}

.profile-card {
  margin: 0 $app-page-gutter;
  padding: 0 4px 12px;
}

.profile-main {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  -webkit-tap-highlight-color: transparent;

  &:active {
    opacity: 0.92;
  }
}

.profile-info {
  flex: 1;
  min-width: 0;

  .nick-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 2px;
  }

  .nick {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: $color-text-title;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .level-tag {
    flex-shrink: 0;
    padding: 1px 8px;
    border-radius: $radius-pill;
    font-size: 10px;
    font-weight: 600;
    text-decoration: none;
    line-height: 1.6;

    &.level-default {
      background: rgba(255, 255, 255, 0.15);
      color: rgba(255, 255, 255, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.2);
    }

    &.level-silver {
      background: $level-silver;
      color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.35);
    }

    &.level-gold {
      background: $level-gold;
      color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.35);
    }
  }

  .account {
    margin: 0;
    font-size: 12px;
    color: $color-text-muted;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.exp-bar-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  cursor: pointer;

  .exp-bar {
    flex: 1;
    height: 6px;
    background: rgba(255, 255, 255, 0.15);
    border-radius: 3px;
    overflow: hidden;
    min-width: 60px;
  }

  .exp-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, $level-gold-soft, $level-gold);
    border-radius: 3px;
    transition: width 0.6s ease;
  }

  .exp-bar-text {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.55);
    white-space: nowrap;
    line-height: 1;
  }
}

.profile-arrow {
  flex-shrink: 0;
  font-size: 16px;
  color: $color-text-disabled;
}

.wallet-strip-top {
  display: flex;
  align-items: center;
  margin: 8px $app-page-gutter 0;
  padding: 14px 0 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.wallet-item-top {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  cursor: pointer;

  &:active {
    opacity: 0.8;
  }
}

.wallet-value-top {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  line-height: 1.3;
}

.wallet-label-top {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.2;
}

.order-card,
.menu-card,
.discover-card {
  margin: 0 $app-page-gutter;
  overflow: hidden;
}

.order-card {
  padding: 14px 16px 16px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;

  h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }

  .link-more {
    font-size: 13px;
    color: $color-text-muted;
    text-decoration: none;

    &:hover {
      color: $color-primary;
    }
  }
}

.order-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 4px;
}

.order-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 10px 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: $color-text-body;
  font-size: 12px;
  border-radius: $radius-btn;
  transition: background $transition-fast, color $transition-fast, transform $transition-fast;

  &:hover {
    background: $color-primary-muted;
    color: $color-primary;
  }

  &:active {
    transform: scale(0.96);
  }
}

.menu-card {
  padding: 4px 0;
}

.menu-title {
  margin: 0;
  padding: 14px 16px 8px;
  font-size: 16px;
  font-weight: 600;
}

.menu-grid {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 4px 0 8px;
}

.menu-item {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border: 0;
  background: transparent;
  width: 100%;
  text-align: left;
  cursor: pointer;
  font: inherit;
  text-decoration: none;
  color: $color-text-title;
  font-size: 13px;
  border-radius: $radius-btn;
  transition: background $transition-fast;

  &:hover {
    background: rgba($color-primary, 0.04);
    color: $color-primary;

    .menu-icon {
      color: $color-primary;
    }
  }

  .menu-label {
    line-height: 1.2;
    text-align: center;
  }

  .menu-icon {
    color: $color-text-muted;
  }
}

.discover-card {
  padding: 0 0 12px;
}

.discover-tabs {
  padding: 0 12px;
  border-bottom: 1px solid $color-border;
}

.discover-tab {
  flex: 1;
  padding: 12px 8px;
  border: none;
  background: transparent;
  font-size: 14px;
  color: $color-text-body;
  cursor: pointer;
  position: relative;

  &.active {
    color: $color-primary;
    font-weight: 600;

    &::after {
      content: '';
      position: absolute;
      left: 50%;
      bottom: 0;
      transform: translateX(-50%);
      width: 28px;
      height: 3px;
      border-radius: $radius-xs;
      background: linear-gradient(90deg, $color-primary, $color-primary-hover);
    }
  }
}

.discover-body {
  padding: 12px 12px 4px;
  min-height: 120px;
}

.feed-sentinel {
  padding: 16px 0;
  text-align: center;
}

.feed-tip {
  margin: 0;
  font-size: 12px;
  color: $color-text-muted;
}

.recommend-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.review-item {
  display: block;
  width: 100%;
  padding: 12px 4px;
  border: none;
  border-bottom: 1px solid $color-border;
  background: $color-bg;
  text-align: left;
  cursor: pointer;
  position: relative;
  z-index: 1;

  &:last-child {
    border-bottom: none;
  }

  &:active {
    background: rgba($color-primary, 0.04);
  }

  .review-cover,
  .review-thumbs img {
    filter: none !important;
    opacity: 1 !important;
  }

  .product-name,
  .review-text {
    color: $color-text-title !important;
  }
}

.review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;

  .review-cover {
    width: 40px;
    height: 40px;
    border-radius: $radius-xs;
    object-fit: cover;
    flex-shrink: 0;
    background: $color-bg-subtle;
  }

  .product-name {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: $color-text-title;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    .more-products-btn {
      display: inline;
      margin-left: 4px;
      padding: 1px 5px;
      border-radius: $radius-xs;
      background: $color-warning-soft;
      color: $color-warning;
      font-size: 10px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
    }
  }
}

.review-thumbs {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;

  img {
    width: 56px;
    height: 56px;
    object-fit: cover;
    border-radius: $radius-xs;
    background: $color-bg-subtle;
  }
}

.review-text {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.5;
  color: $color-text-body;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.review-biz-reply,
.review-reply {
  margin: 0 0 6px;
  font-size: 12px;
  line-height: 1.45;
  color: $color-text-muted;

  .tag {
    display: inline-block;
    margin-right: 6px;
    padding: 0 6px;
    border-radius: $radius-xs;
    background: $color-primary-muted;
    color: $color-primary;
    font-size: 11px;
  }
}

.review-biz-reply {
  padding: 8px 10px;
  border-radius: $radius-xs;
  background: $color-bg-subtle;
  color: $color-text-body;
}

.review-time {
  margin: 0;
  font-size: 11px;
  color: $color-text-disabled;
}

.discover-tip {
  margin: 0;
  text-align: center;
  font-size: 12px;
  color: $color-text-muted;
  padding: 16px 0;
}

.load-more-btn {
  display: block;
  width: 100%;
  margin-top: 8px;
  padding: 10px;
  border: none;
  background: transparent;
  font-size: 13px;
  color: $color-primary;
  cursor: pointer;
}

@media (min-width: $breakpoint-tablet) {
  .recommend-grid {
    grid-template-columns: repeat(6, 1fr);
    gap: 10px;
  }
}
</style>
