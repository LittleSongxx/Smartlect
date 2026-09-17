<template>
  <div class="pc-search-result">
    <section class="filter-panel">
      <div class="search-row">
        <el-input v-model="query.keyWords" placeholder="搜索关键词" clearable @keyup.enter="onSearch" class="search-input">
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
          <template #append>
            <el-button @click="onSearch">搜索</el-button>
          </template>
        </el-input>
      </div>
      <div class="filter-row">
        <div class="filter-group">
          <span class="filter-label">价格</span>
          <el-input v-model="query.priceFrom" placeholder="最低价" class="price-input" />
          <span class="sep">—</span>
          <el-input v-model="query.priceTo" placeholder="最高价" class="price-input" />
        </div>
        <div class="filter-group">
          <span class="filter-label">排序</span>
          <el-select v-model="sortMode" placeholder="排序" clearable class="sort-select" @change="onSortChange">
            <el-option label="综合" value="" />
            <el-option label="价格从低到高" value="price-asc" />
            <el-option label="价格从高到低" value="price-desc" />
            <el-option label="销量" value="sale" />
          </el-select>
        </div>
      </div>
    </section>

    <section class="result-panel">
      <h3 class="result-title">「{{ activeKeywords }}」共 {{ total }} 件</h3>
      <div v-if="list.length" class="pc-result-grid">
        <PcProductTile
          v-for="p in list"
          :key="p.productId"
          :product="p"
          @click="goDetail"
        />
      </div>
      <el-empty v-else-if="!loading" description="暂无搜索结果">
        <el-button type="primary" @click="$router.push('/')">去首页</el-button>
      </el-empty>
      <div ref="sentinelRef" class="load-sentinel" />
      <p v-if="loadingMore" class="load-tip">加载中…</p>
      <p v-else-if="finished && list.length" class="load-tip">没有更多了</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import PcProductTile from '@/components/pc/PcProductTile.vue';
import { useSearchPage } from '@/composables/useSearchPage';

// 与移动端搜索结果页共用同一份查询/分页/缓存逻辑；这里只剩 PC 模板需要的绑定
const {
  query, sortMode, activeKeywords, loadError,
  total, list, loading, loadingMore, finished,
  sentinelRef, onSearch, onSortChange, goDetail
} = useSearchPage({ scope: 'pc' });
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.pc-search-result {
  display: flex;
  flex-direction: column;
  gap: 16px;
  animation: fadeSlideUp 0.6s cubic-bezier(0.25, 0.1, 0.25, 1) both;
}

@keyframes fadeSlideUp {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.filter-panel {
  border: 1px solid $color-border;
  border-radius: $radius-card;
  background: $color-card;
  padding: 20px 24px;
  box-shadow: $shadow-card;
  transition: box-shadow $transition-normal;
}

.search-row {
  margin-bottom: 16px;
}

.search-input {
  :deep(.el-input-group__append) {
    .el-button {
      font-weight: 500;
    }
  }
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 20px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-label {
  font-size: 13px;
  color: $color-text-muted;
  font-weight: 500;
  flex-shrink: 0;
}

.price-input {
  width: 100px;

  :deep(.el-input__wrapper) {
    border-radius: $radius-xs;
  }
}

.sort-select {
  width: 140px;

  :deep(.el-input__wrapper) {
    border-radius: $radius-xs;
  }
}

.sep {
  color: $color-text-muted;
  font-size: 13px;
}

.result-panel {
  border: 1px solid $color-border;
  border-radius: $radius-card;
  background: $color-card;
  padding: 20px 24px;
  box-shadow: $shadow-card;
}

.result-title {
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 600;
  color: $color-text-primary;
  letter-spacing: 0;
}

.pc-result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax($pc-product-tile-min-width, 1fr));
  gap: 14px;
  align-items: start;
}

.load-sentinel {
  height: 1px;
}

.load-tip {
  text-align: center;
  font-size: 12px;
  color: $color-text-muted;
  padding: 12px 0;
}
</style>
