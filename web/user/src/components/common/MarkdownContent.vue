<template>
  <div v-if="content" class="markdown-content" :class="{ 'is-image-center': centerImages }" v-html="html" />
  <p v-else class="markdown-empty">{{ emptyText }}</p>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import MarkdownIt from 'markdown-it';
import { isAllowedProductImageSrc } from '@/utils/productDesc';

const props = withDefaults(defineProps<{
  content?: string | null;
  emptyText?: string;
  allowImages?: boolean;
  centerImages?: boolean;
  citeMarks?: boolean;
}>(), { emptyText: '暂无内容', allowImages: false, centerImages: false, citeMarks: false });

function createRenderer(allowImages: boolean) {
  const md = new MarkdownIt({ html: false, breaks: true, linkify: false });
  if (!allowImages) {
    md.disable(['image', 'link', 'autolink']);
    return md;
  }
  md.disable(['link', 'autolink']);
  const defaultImage = md.renderer.rules.image;
  md.renderer.rules.image = (tokens, idx, options, env, self) => {
    const src = tokens[idx]?.attrGet('src') || '';
    if (!isAllowedProductImageSrc(src)) return '';
    return defaultImage ? defaultImage(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options);
  };
  return md;
}

const assistantMd = createRenderer(false);
const productMd = createRenderer(true);
const html = computed(() => {
  const rendered = (props.allowImages ? productMd : assistantMd).render(props.content || '');
  if (!props.citeMarks) return rendered;
  return rendered.replace(/\[(\d{1,2})\]/g, '<sup class="cite-num">$1</sup>');
});
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.markdown-content {
  font-size: 14px;
  line-height: 1.6;
  color: $color-text-body;
  word-break: break-word;

  :deep(img) {
    display: block;
    max-width: 100%;
    height: auto;
    margin: 8px 0;
    border-radius: $radius-xs;
    cursor: zoom-in;
  }

  :deep(p) {
    margin: 8px 0;
  }

  :deep(p:first-child) {
    margin-top: 0;
  }

  :deep(p:last-child) {
    margin-bottom: 0;
  }

  :deep(ul),
  :deep(ol) {
    margin: 8px 0;
    padding-left: 1.25em;
  }

  :deep(li) {
    margin: 4px 0;
    line-height: 1.65;
  }

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4) {
    margin: 12px 0 6px;
    font-size: 15px;
    font-weight: 600;
    line-height: 1.4;
    color: $color-text-title;
  }

  :deep(h1:first-child),
  :deep(h2:first-child),
  :deep(h3:first-child) {
    margin-top: 0;
  }

  :deep(a) {
    color: $color-primary;
    text-decoration: none;
  }

  :deep(table) {
    width: 100%;
    margin: 10px 0;
    border-collapse: collapse;
    font-size: 13px;
    line-height: 1.45;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid $color-border;
    padding: 8px 10px;
    text-align: left;
    vertical-align: top;
  }

  :deep(th) {
    background: $color-bg-subtle;
    color: $color-text-title;
    font-weight: 600;
  }

  :deep(td) {
    color: $color-text-body;
  }

  :deep(sup.cite-num) {
    margin-left: 1px;
    font-size: 11px;
    font-weight: 650;
    line-height: 0;
    color: $color-primary;
    vertical-align: super;
  }

  &.is-image-center {
    :deep(img) {
      margin-left: auto;
      margin-right: auto;
    }

    :deep(p:has(> img:only-child)),
    :deep(figure) {
      text-align: center;
    }
  }
}

.markdown-empty {
  margin: 0;
  font-size: 13px;
  color: $color-text-muted;
}
</style>
