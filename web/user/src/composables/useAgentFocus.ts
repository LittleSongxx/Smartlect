import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';
import { loadAgentConsultProduct } from '@/utils/agentProductConsult';

export type AgentFocusMode = 'GLOBAL' | 'PRODUCT';

const PRODUCT_TIPS = ['成分有哪些', '规格怎么选', '包装是什么样', '这件怎么退'];
const GLOBAL_TIPS = ['运费怎么算', '退换货政策', '帮我选一件', '查询我的订单'];

const focusMode = ref<AgentFocusMode>('GLOBAL');
const focusPinned = ref(false);

export function resetAgentFocus() {
  focusMode.value = 'GLOBAL';
  focusPinned.value = false;
}

export function useAgentFocus() {
  const route = useRoute();
  const panel = usePcAgentPanelStore();
  const auth = useAuthStore();

  const productId = computed(() => {
    if (typeof route.params.productId === 'string' && route.params.productId) return route.params.productId;
    if (typeof route.query.product === 'string' && route.query.product) return route.query.product;
    return '';
  });
  const skuKey = computed(() => {
    if (typeof route.query.sku === 'string' && route.query.sku) return route.query.sku;
    return panel.skuKey || '';
  });
  const productName = computed(() => {
    const saved = loadAgentConsultProduct(auth.userInfo?.userId as string | undefined);
    return saved && saved.productId === productId.value ? saved.productName : '';
  });
  const focused = computed(() => focusMode.value === 'PRODUCT' && !!productId.value);
  const tips = computed(() => (focused.value ? PRODUCT_TIPS : GLOBAL_TIPS));

  watch(productId, (id, prev) => {
    if (!id) {
      focusMode.value = 'GLOBAL';
      focusPinned.value = false;
      return;
    }
    if (prev && id !== prev) {
      focusPinned.value = false;
      focusMode.value = 'PRODUCT';
      return;
    }
    if (!focusPinned.value && prev !== id) focusMode.value = 'PRODUCT';
  }, { immediate: true });

  function setGlobal() {
    focusMode.value = 'GLOBAL';
    focusPinned.value = true;
  }

  function setProduct() {
    if (productId.value) {
      focusMode.value = 'PRODUCT';
      focusPinned.value = true;
    }
  }

  function payload() {
    return {
      focus_mode: focused.value ? 'PRODUCT' as const : 'GLOBAL' as const,
      ...(focused.value && productId.value ? { product_id: productId.value } : {}),
      ...(focused.value && skuKey.value ? { sku_key: skuKey.value } : {})
    };
  }

  return { focusMode, focused, productId, productName, skuKey, tips, setGlobal, setProduct, payload };
}
