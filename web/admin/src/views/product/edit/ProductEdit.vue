<template>
  <div class="form-style">
    <div v-if="route.params.productId" class="ai-status-bar" :class="aiStatus">
      <span class="ai-label">导购可见性</span>
      <strong>{{ aiStatusText }}</strong>
      <span v-if="aiDetail" class="ai-detail">{{ aiDetail }}</span>
      <el-button v-if="aiStatus === 'failed'" size="small" type="primary" :loading="aiBusy" @click="retryProjection">
        重新投影
      </el-button>
    </div>
    <el-tabs v-model="activeName" @tab-click="tabClick">
      <el-tab-pane label="基础信息" name="base">
        <ProductBase :productInfo="productInfo"></ProductBase>
      </el-tab-pane>
      <el-tab-pane label="SKU信息" name="sku">
        <div class="content-panel">
          <ProductSkuProperty></ProductSkuProperty>
          <ProductSkuList></ProductSkuList>
        </div>
      </el-tab-pane>
    </el-tabs>
    <div class="post-panel">
      <el-button @click="cancelPost" link>取消</el-button>
      <el-button @click="submitProduct()" type="primary">发布商品</el-button>
    </div>
  </div>
</template>

<script setup>
import ProductSkuList from './ProductSkuList.vue'
import ProductSkuProperty from './ProductSkuProperty.vue'
import ProductBase from './ProductBase.vue'
import { ref, getCurrentInstance, computed, onMounted, onUnmounted, watch } from 'vue'
import { aiGet, aiWrite } from '@/api/client'
const { proxy } = getCurrentInstance()
import { useRouter, useRoute } from 'vue-router'
const router = useRouter()
const route = useRoute()

import { useProductEditStore } from '@/stores/productEditStore'
const productEditStore = useProductEditStore()

const activeName = ref('base')
const productListPath = () => '/product'

const tabClick = async (e) => {
  if (e.paneName == 'sku' && !productInfo.value.categoryId) {
    proxy.Message.warning('请先选择分类')
    return
  }
}

const CONTENT_KEYS = ['selling_points', 'usage', 'ingredients', 'packaging', 'contraindications', 'after_sale_note']

const emptyProduct = () => ({
  cover: Array(proxy.productMainImageCount).fill(''),
  brand: '',
  selling_points: '',
  usage: '',
  ingredients: '',
  packaging: '',
  contraindications: '',
  after_sale_note: '',
})

const productInfo = ref(emptyProduct())
const aiStatus = ref('idle')
const aiDetail = ref('')
const aiBusy = ref(false)
let aiTimer

const aiStatusText = computed(() => ({
  visible: 'AI 已可见',
  indexing: '索引中',
  failed: '投影失败',
  idle: '尚未投影',
}[aiStatus.value] || '尚未投影'))

const applyContent = (info) => {
  let parsed = {}
  try {
    parsed = info.contentJson ? JSON.parse(info.contentJson) : {}
  } catch {
    parsed = {}
  }
  for (const key of CONTENT_KEYS) {
    info[key] = parsed[key] || ''
  }
  if (!info.productDesc && parsed.extra_markdown) {
    info.productDesc = parsed.extra_markdown
  }
  if (info.productDesc) {
    info.productDesc = String(info.productDesc).replaceAll('/api/file/getResource', '/admin-api/file/getResource')
  }
  info.brand = info.brand || ''
  return info
}

const buildContentJson = (info) => {
  const content = {
    extra_markdown: String(info.productDesc || '').replaceAll('/admin-api/file/getResource', '/api/file/getResource'),
  }
  for (const key of CONTENT_KEYS) {
    if (info[key]?.trim()) content[key] = info[key].trim()
  }
  return JSON.stringify(content)
}

const loadAiStatus = async () => {
  const productId = route.params.productId
  if (!productId) return
  if (aiTimer) {
    window.clearTimeout(aiTimer)
    aiTimer = undefined
  }
  try {
    const data = await aiGet(`/productProjection/${encodeURIComponent(productId)}`)
    aiStatus.value = data.ai_status || 'idle'
    const job = data.job || {}
    const indexJob = data.index_job || {}
    aiDetail.value = job.message || indexJob.state || ''
    if (aiStatus.value === 'indexing') {
      aiTimer = window.setTimeout(loadAiStatus, 4000)
    }
  } catch {
    aiStatus.value = 'idle'
    aiDetail.value = ''
  }
}

const retryProjection = async () => {
  const productId = route.params.productId
  if (!productId) return
  aiBusy.value = true
  try {
    await aiWrite(`/productProjection/${encodeURIComponent(productId)}/retry`, {})
    aiStatus.value = 'indexing'
    await loadAiStatus()
  } catch (error) {
    proxy.Message.error(error.message || '重投影失败')
  } finally {
    aiBusy.value = false
  }
}

const getProductInfo = async () => {
  if (!route.params.productId) {
    return
  }
  let result = await proxy.Request({
    url: proxy.Api.getProductInfo,
    params: {
      productId: route.params.productId,
    },
  })
  if (!result) {
    return
  }
  productInfo.value = applyContent({
    ...emptyProduct(),
    ...result.data.productInfo,
    cover: (result.data.productInfo.cover || '').split(',').filter(Boolean),
  })
  loadAiStatus()
  productEditStore.productPropertyList = result.data.productPropertyList.map((property) => ({
    ...property,
    propertyValues: property.propertyValues.map((value) => {
      const gallery = String(value.propertyGallery || '').split(',').filter(Boolean)
      return {
        ...value,
        propertyCover: value.propertyCover || '',
        // 图集编辑用固定槽位数组，保存时再 join 回逗号串
        propertyGalleryArray: [
          ...gallery,
          ...Array(Math.max(0, proxy.productMainImageCount - gallery.length)).fill(''),
        ],
      }
    }),
  }))
  productEditStore.skuData = new Map(
    result.data.skuList.map((sku) => [sku.propertyValueIdHash, sku])
  )
  productEditStore.excludedSkuHashes = new Set()
}

const cancelPost = () => {
  router.push(productListPath())
}

const submitProduct = async (sensitiveConfirmPwd) => {
  // @click 可能传入 MouseEvent；仅字符串才视为已确认的管理员密码
  const confirmPwd = typeof sensitiveConfirmPwd === 'string' ? sensitiveConfirmPwd : undefined
  activeName.value = 'base'
  if (!productInfo.value.cover.every((item) => item !== '' && item != null)) {
    proxy.Message.warning('请上传商品主图')
    return
  }
  if (!productInfo.value.productName?.trim()) {
    proxy.Message.warning('请输入商品名称')
    return
  }

  if (!productInfo.value.productDesc?.trim()) {
    proxy.Message.warning('请输入商品描述')
    return
  }
  activeName.value = 'sku'
  if (productEditStore.skuList.length === 0) {
    proxy.Message.warning('请先设置SKU属性并生成SKU列表')
    return
  }

  for (const property of productEditStore.productPropertyList) {
    for (const [index, value] of property.propertyValues.entries()) {
      // 图集传了而色卡没传时，用图集首张兜底，保证订单/购物车快照有图可用
      const gallery = (value.propertyGalleryArray || []).filter(Boolean)
      if (property.coverType === 1 && !value.propertyCover && gallery.length) {
        value.propertyCover = gallery[0]
      }
      if (property.coverType === 1 && !value.propertyCover) {
        proxy.Message.warning(
          `请上传【${property.propertyName}】属性第(${index + 1})行的图片`
        )
        return
      }
      if (!value.propertyValue.trim()) {
        proxy.Message.warning(
          `请填写【${property.propertyName}】属性第(${index + 1})行的值`
        )
        return
      }
    }
  }

  for (const [index, sku] of productEditStore.skuList.entries()) {
    if (sku.price <= 0) {
      proxy.Message.warning(`请设置sku列表第(${index + 1})行的价格`)
      return
    }
  }

  const productInfoResultData = { ...productInfo.value }
  productInfoResultData.cover = productInfoResultData.cover.join(',')
  productInfoResultData.pCategoryId = productInfoResultData.categoryId[0]
  productInfoResultData.categoryId = productInfoResultData.categoryId[1]
  productInfoResultData.brand = (productInfoResultData.brand || '').trim()
  productInfoResultData.productDesc = String(productInfoResultData.productDesc || '').replaceAll('/admin-api/file/getResource', '/api/file/getResource')
  productInfoResultData.contentJson = buildContentJson(productInfoResultData)
  for (const key of CONTENT_KEYS) {
    delete productInfoResultData[key]
  }

  const productPropertyListResultData = []
  for (let property of productEditStore.productPropertyList) {
    for (let [index, propertyValue] of property.propertyValues.entries()) {
      const resultValue = {
        ...property,
        ...propertyValue,
        propertyGallery: (propertyValue.propertyGalleryArray || []).filter(Boolean).join(','),
        sort: index,
      }
      delete resultValue.categoryId
      delete resultValue.pCategoryId
      delete resultValue.propertyValues
      delete resultValue.propertyGalleryArray
      productPropertyListResultData.push(resultValue)
    }
  }

  const skuListResultData = []
  for (let [index, sku] of productEditStore.skuList.entries()) {
    skuListResultData.push({
      price: sku.price,
      stock: sku.stock,
      sort: index,
      propertyValueIdHash: sku.propertyValueIdHash,
      propertyValueIds: sku.propertyValueIds,
    })
  }

  const doSave = async (confirmPwd) => {
    let result = await proxy.Request({
      url: route.params.productId ? proxy.Api.updateProduct : proxy.Api.addProduct,
      dataType: 'json',
      sensitiveConfirmPwd: confirmPwd,
      params: {
        productInfo: productInfoResultData,
        productPropertyList: productPropertyListResultData,
        skuList: skuListResultData,
      },
    })
    if (!result) {
      return
    }
    proxy.Message.success('保存成功，正在投影给导购')
    const savedId = result.data || route.params.productId || productInfoResultData.productId
    if (savedId && !route.params.productId) {
      await router.replace({ name: 'updateProduct', params: { productId: savedId } })
    }
    if (savedId) {
      aiStatus.value = 'indexing'
      await loadAiStatus()
      return
    }
    router.push(productListPath())
  }

  if (route.params.productId && !confirmPwd) {
    proxy.ConfirmSensitive({
      message: '保存将更新价格、库存，并投影给导购知识库。是否继续？',
      okfun: doSave,
    })
    return
  }

  await doSave(confirmPwd)
}

const reset = () => {
  productInfo.value = emptyProduct()
  productEditStore.resetSkuState()
}

onMounted(() => {
  reset()
  getProductInfo()
})

watch(() => route.params.productId, (id, prev) => {
  if (id && id !== prev) {
    getProductInfo()
  }
})

onUnmounted(() => {
  if (aiTimer) window.clearTimeout(aiTimer)
})
</script>

<style lang="scss" scoped>
.form-style {
  position: relative;

  .ai-status-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin: 0 0 12px;
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid #e8e4dc;
    background: #faf8f4;
    font-size: 13px;
    color: #5c574e;
  }

  .ai-label {
    color: #8a8478;
  }

  .ai-detail {
    color: #8a8478;
  }

  .ai-status-bar.visible {
    border-color: #c9e6d3;
    background: #f3faf5;
    color: #24553a;
  }

  .ai-status-bar.indexing {
    border-color: #ead9a8;
    background: #fff8e8;
    color: #7a4b00;
  }

  .ai-status-bar.failed {
    border-color: #f0c6c2;
    background: #fff5f4;
    color: #8a1c14;
  }

  .post-panel {
    position: absolute;
    top: 3px;
    right: 20px;
  }

  .content-panel {
    display: flex;
    height: calc(100vh - 130px);
  }

}
</style>
