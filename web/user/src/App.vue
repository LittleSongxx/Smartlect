<template>
  <el-config-provider :locale="zhCn" :size="elementSize">
    <div class="page-texture" />
    <RouterView />
    <ProductSkuSheet />
    <ImagePreviewHost />
    <PcAgentFloatingPanel v-if="isDesktop" />
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { RouterView } from 'vue-router';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import ProductSkuSheet from '@/components/business/ProductSkuSheet.vue';
import ImagePreviewHost from '@/components/common/ImagePreviewHost.vue';
import PcAgentFloatingPanel from '@/components/pc/PcAgentFloatingPanel.vue';
import { useDeviceStore } from './stores/device';
import { useAuthStore } from './stores/auth';
import { recordLanding } from '@/api/traffic';
import { loadSession } from '@/api/client';

const deviceStore = useDeviceStore();
const elementSize = computed(() => (deviceStore.isDesktop ? 'small' : 'default'));
const isDesktop = computed(() => deviceStore.isDesktop);

useAuthStore().tryRestoreSession();

onMounted(() => {
  deviceStore.sync();
  void loadSession().catch(() => undefined);
  void recordLanding();
});
</script>
