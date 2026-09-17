<template>
  <div class="search-result-page">
    <div class="card filter-card filter-sticky">
      <div class="search-row">
        <el-input
          v-model="query.keyWords"
          size="small"
          placeholder="搜索关键词"
          clearable
          class="search-keyword"
          @keyup.enter="onSearch"
        />
        <el-button size="small" type="primary" class="search-submit" @click="onSearch">搜索</el-button>
      </div>
      <div class="filter-conditions toolbar-form toolbar-row">
        <el-input
          v-model="query.priceFrom"
          size="small"
          placeholder="最低价"
          class="toolbar-form-price"
        />
        <span class="toolbar-form-sep">—</span>
        <el-input v-model="query.priceTo" size="small" placeholder="最高价" class="toolbar-form-price" />
        <el-select
          v-model="sortMode"
          size="small"
          placeholder="排序"
          class="toolbar-form-sort toolbar-form-sort--wide"
          clearable
          teleported
          :popper-options="{ strategy: 'fixed' }"
          @change="onSortChange"
        >
          <el-option label="综合" value="" />
          <el-option label="价格从低到高" value="price-asc" />
          <el-option label="价格从高到低" value="price-desc" />
          <el-option label="销量" value="sale" />
        </el-select>
      </div>
    </div>

    <div class="card result-card">
      <div class="card-section-title">
        <h3>「{{ activeKeywords }}」共 {{ total }} 件</h3>
      </div>
      <div v-if="list.length" class="product-grid product-grid--dense">
        <ProductCard v-for="p in list" :key="p.productId" :product="p" compact @click="goDetail" />
      </div>
      <div v-else-if="loadError && !loading" class="page-empty">
        <el-empty :description="loadError">
          <el-button type="primary" @click="resetAndLoad">重试</el-button>
        </el-empty>
      </div>
      <div v-else-if="!loading" class="page-empty">
        <el-empty description="暂无搜索结果">
          <el-button type="primary" @click="$router.push('/')">去首页</el-button>
        </el-empty>
      </div>
      <div ref="sentinelRef" class="load-sentinel" />
      <p v-if="loadingMore" class="load-tip">加载中…</p>
      <p v-else-if="finished && list.length" class="load-tip">没有更多了</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import ProductCard from '@/components/business/ProductCard.vue';
import { useSearchPage } from '@/composables/useSearchPage';

// 查询状态、分页、缓存、店铺同步与路由监听都在 useSearchPage 里（PC 版共用同一份）
const {
  query, sortMode, activeKeywords, loadError,
  total, list, loading, loadingMore, finished,
  sentinelRef, onSearch, onSortChange, goDetail, resetAndLoad
} = useSearchPage({ scope: 'mobile' });
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.filter-sticky {
  position: sticky;
  top: 0;
  z-index: 30;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: $color-card;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
  overflow: visible;
}

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;

  .search-keyword {
    flex: 1;
    min-width: 0;
  }

  .search-submit {
    flex-shrink: 0;
    min-width: 56px;
    font-weight: 600;
  }
}

.filter-conditions {
  padding-top: 2px;
  flex-wrap: wrap;
  overflow: visible;
  row-gap: 8px;
}

.filter-conditions :deep(.toolbar-form-sort--wide) {
  width: 118px;
}

.result-card {
  padding: 12px;
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
