import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { detectDevicePlatform, type DevicePlatform } from '@/utils/device';

export const useDeviceStore = defineStore('device', () => {
  const platform = ref<DevicePlatform>(detectDevicePlatform());

  const isMobile = computed(() => platform.value === 'mobile');
  const isDesktop = computed(() => platform.value === 'desktop');

  const applyPlatform = (next: DevicePlatform) => {
    platform.value = next;
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.platform = next;
    }
  };

  const sync = () => {
    applyPlatform(detectDevicePlatform());
  };

  return {
    platform,
    isMobile,
    isDesktop,
    sync
  };
});
