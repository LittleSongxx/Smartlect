<template>
  <div class="json-collapse">
    <el-collapse>
      <el-collapse-item>
        <template #title>
          <span class="json-collapse__title">{{ title }}</span>
        </template>
        <div class="json-collapse__bar">
          <el-button size="small" :icon="DocumentCopy" @click="copy">{{ copied ? '已复制' : '复制 JSON' }}</el-button>
        </div>
        <pre class="json-collapse__body">{{ body }}</pre>
        <slot />
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { DocumentCopy } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  title: { type: String, default: '原始数据' },
  value: { type: [Object, Array, String, Number, Boolean], default: null },
})

const copied = ref(false)

const body = computed(() =>
  typeof props.value === 'string' ? props.value : JSON.stringify(props.value, null, 2),
)

const copy = async () => {
  try {
    await navigator.clipboard.writeText(body.value || '')
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}
</script>

<style scoped lang="scss">
.json-collapse {
  :deep(.el-collapse-item__header) {
    font-size: 13px;
    color: var(--primary);
  }

  &__title {
    padding-left: 2px;
  }

  &__bar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 8px;
  }

  &__body {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    margin: 0;
    padding: 12px;
    background: var(--detail-bg);
    border-radius: var(--card-radius);
    font-size: var(--detail-fs);
    font-family: var(--mono-font);
    line-height: 1.6;
    max-height: 360px;
    overflow: auto;
    color: var(--text2);
  }
}
</style>
