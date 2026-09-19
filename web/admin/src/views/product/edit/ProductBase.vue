<template>

  <el-form class="form-style" label-width="auto" @submit.prevent>
    <el-form-item label="主图">
      <div class="cover-list">
        <ImageSelect
          v-for="(_, index) in proxy.productMainImageCount"
          :key="index"
          v-model="productInfo.cover[index]"
          :cutWidth="250"
          :width="120"
        />
      </div>
    </el-form-item>
    <el-form-item label="商品名称" prop="productName">
      <el-input v-model="productInfo.productName" placeholder="请输入商品名称" clearable></el-input>
    </el-form-item>
    <el-form-item label="分类" prop="categoryIdArray">
      <el-cascader
        v-model="productInfo.categoryId"
        :options="categoryList"
        :props="{ label: 'categoryName', value: 'categoryId' }"
        :style="{ width: '300px' }"
        @change="getProductPropertyList"
        :disabled="route.params.productId != null"
      />
    </el-form-item>
    <el-form-item label="品牌" prop="brand">
      <el-input v-model="productInfo.brand" maxlength="100" placeholder="选填，内容轴，不参与 SKU" clearable style="width: 300px" />
    </el-form-item>
    <el-form-item v-for="section in contentSections" :key="section.key" :label="section.label">
      <el-input
        v-model="productInfo[section.key]"
        type="textarea"
        :rows="3"
        :placeholder="section.placeholder"
        maxlength="4000"
        show-word-limit
      />
    </el-form-item>
    <el-form-item label="商品描述" prop="productDesc">
      <div class="product-desc">
        <EditorMarkdown v-model="productInfo.productDesc"></EditorMarkdown>
      </div>
    </el-form-item>
  </el-form>
</template>

<script setup>
import EditorMarkdown from '@/components/markdown/EditorMarkdown.vue'
import ImageSelect from '@/components/ImageSelect.vue'
import { ref, getCurrentInstance, onMounted, watch } from 'vue'
const { proxy } = getCurrentInstance()
import { useRoute } from 'vue-router'
const route = useRoute()

import { useProductEditStore } from '@/stores/productEditStore'
import { createPropertyValue } from './valueTemplate.js'
const productEditStore = useProductEditStore()

const props = defineProps({
  productInfo: {
    type: Object,
    default: () => ({}),
  },
})

const contentSections = [
  { key: 'selling_points', label: '卖点', placeholder: '选填，投影为商品知识「卖点」' },
  { key: 'usage', label: '用法', placeholder: '选填，例如每日两次、用量' },
  { key: 'ingredients', label: '成分', placeholder: '选填，独特事实需可核对' },
  { key: 'packaging', label: '包装', placeholder: '选填，规格轴仍在 SKU 页填写' },
  { key: 'contraindications', label: '禁忌', placeholder: '选填，过敏或不宜人群' },
  { key: 'after_sale_note', label: '售后备注', placeholder: '选填，本商品售后说明' },
]

const categoryList = ref([])
const loadCategory = async () => {
  let result = await proxy.Request({
    url: proxy.Api.loadCategory,
    params: {
      queryProperty: true,
    },
  })
  if (!result) {
    return
  }
  categoryList.value = result.data
}

const createPropertyWithDefaultValue = (property, index = 0) => ({
  ...property,
  propertyValues: [createPropertyValue(proxy.productMainImageCount, index)],
})

const getProductPropertyList = (data) => {
  applyCategoryPropertyTemplates(data[data.length - 1], true)
}

const syncCategoryPropertyTemplates = (categoryId) => {
  if (!categoryId || !categoryList.value.length) return
  applyCategoryPropertyTemplates(categoryId, false)
}

const findPathToNode = (id, nodes, path = []) => {
  for (const node of nodes) {
    const nextPath = [...path, node]
    if (node.categoryId === id) return nextPath
    if (node.children?.length) {
      const found = findPathToNode(id, node.children, nextPath)
      if (found) return found
    }
  }
  return null
}

const collectCategoryPropertyTemplates = (categoryId) => {
  const id = Array.isArray(categoryId) ? categoryId[categoryId.length - 1] : categoryId
  if (!id || !categoryList.value.length) return []
  const path = findPathToNode(id, categoryList.value)
  if (!path?.length) return []
  const seen = new Set()
  const templates = []
  for (const node of path) {
    for (const property of node.productPropertyList || []) {
      if (!property?.propertyId || seen.has(property.propertyId)) continue
      seen.add(property.propertyId)
      templates.push(createPropertyWithDefaultValue(property, templates.length))
    }
  }
  return templates
}

const applyCategoryPropertyTemplates = (categoryId, resetActiveList = true) => {
  const templates = collectCategoryPropertyTemplates(categoryId)
  productEditStore.categoryPropertyTemplates = templates.map((item) => ({
    ...item,
    propertyValues: item.propertyValues.map((v) => ({ ...v })),
  }))
  if (resetActiveList) {
    productEditStore.productPropertyList = templates.map((item) => ({
      ...item,
      propertyValues: item.propertyValues.map((v) => ({ ...v })),
    }))
    productEditStore.skuData = new Map()
    productEditStore.excludedSkuHashes = new Set()
  }
}

onMounted(() => {
  loadCategory()
})

watch(
  () => [props.productInfo?.categoryId, categoryList.value.length],
  () => {
    syncCategoryPropertyTemplates(props.productInfo?.categoryId)
  }
)
</script>

<style lang="scss" scoped>
.form-style {
  .cover-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;

    :deep(.cover) {
      margin-right: 10px;
    }

    :deep(.image-upload) {
      margin-right: 10px;
    }
  }
}

.product-desc {
  width: 100%;
  height: calc(100vh - 400px);

  &.is-mobile {
    height: 300px;
    border-radius: 8px;
    overflow: hidden;
  }
}
</style>
