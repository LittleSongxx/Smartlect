<template>
  <el-image
    :src="src"
    :fit="fit"
    :lazy="lazy"
    :alt="altText"
    class="product-image"
    :class="{ 'is-dense': dense }"
    :style="sizeStyle"
    @error="onError"
  >
    <template #placeholder>
      <div class="img-placeholder">
        <el-icon :size="iconSize"><Picture /></el-icon>
      </div>
    </template>
    <template #error>
      <div class="img-placeholder">
        <el-icon :size="iconSize"><Picture /></el-icon>
      </div>
    </template>
  </el-image>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Picture } from '@element-plus/icons-vue';
import { pickProductCover, resolveImageUrl } from '@/utils/image';

const props = withDefaults(
  defineProps<{
    source?: string | null;
    product?: Record<string, any>;
    width?: number | string;
    height?: number | string;
    fit?: 'cover' | 'contain' | 'fill';
    lazy?: boolean;
    useThumbnail?: boolean;
    /** 无障碍文本；不传时用商品名，纯装饰场景显式传空串 */
    alt?: string;

    dense?: boolean;
  }>(),
  { fit: 'cover', lazy: true, useThumbnail: true, dense: false }
);

const rawSource = computed(() => props.source ?? (props.product ? pickProductCover(props.product) : ''));
const altText = computed(() => props.alt ?? String(props.product?.productName ?? ''));

// 主图（useThumbnail=false）请求的是去掉 _thumbnail 的原图。只存了缩略图的商品原图并不
// 存在，服务端现在会回退到缩略图，但已经被缓存成空响应的那条 URL 换不掉——只能在这里失败
// 后换一个 URL 重新取（缩略图那条通常在缓存里是好的）。
const failedFullSize = ref(false);
const onError = () => {
  if (props.useThumbnail === false && !failedFullSize.value) {
    failedFullSize.value = true;
  }
};
watch(rawSource, () => {
  failedFullSize.value = false;
});

const src = computed(() => {
  if (!rawSource.value) return '';
  if (props.useThumbnail || !failedFullSize.value) {
    return resolveImageUrl(rawSource.value, { useThumbnail: props.useThumbnail });
  }
  return resolveImageUrl(rawSource.value, { useThumbnail: true });
});

const toCssSize = (val?: number | string) => {
  if (val == null || val === '') return undefined;
  if (typeof val === 'number' && Number.isFinite(val)) return `${val}px`;
  const text = String(val).trim();
  if (/^\d+(\.\d+)?$/.test(text)) return `${text}px`;
  return text;
};

const sizeStyle = computed(() => ({
  width: toCssSize(props.width) ?? '100%',
  height: toCssSize(props.height) ?? '100%'
}));

const iconSize = computed(() => {
  const w = Number(props.width);
  if (!Number.isNaN(w) && w > 0) return Math.min(32, Math.max(20, Math.floor(w / 3)));
  return 28;
});
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.product-image {
  display: block;
  border-radius: $radius-sm;
  overflow: hidden;
  background: transparent;

  :deep(.el-image) {
    width: 100%;
    height: 100%;
    display: block;
  }

  :deep(.el-image__inner) {
    width: 100%;
    height: 100%;
    max-width: 100%;
    max-height: 100%;
  }
}

.img-placeholder {
  width: 100%;
  height: 100%;
  min-height: 60px;
  display: grid;
  place-items: center;
  color: #ccc;
  background: linear-gradient(135deg, #ffffff, #f8f8f8);
}

.product-image.is-dense .img-placeholder {
  min-height: 0;
}
</style>
