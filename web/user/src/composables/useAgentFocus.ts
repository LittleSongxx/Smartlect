import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';
import { loadAgentConsultProduct } from '@/utils/agentProductConsult';

export type AgentFocusMode = 'GLOBAL' | 'PRODUCT';

const PRODUCT_TIPS = ['成分有哪些', '规格怎么选', '包装是什么样', '这件怎么退'];
const GLOBAL_TIPS = ['运费怎么算', '退换货政策', '帮我选一件', '查询我的订单'];
const FOCUS_STORAGE_PREFIX = 'smartlect:agent-focus:';

const focusMode = ref<AgentFocusMode>('GLOBAL');
const focusPinned = ref(false);

function storageKey(productId: string) {
  return `${FOCUS_STORAGE_PREFIX}${productId}`;
}

function readStoredFocus(productId: string): AgentFocusMode | '' {
  if (!productId || typeof sessionStorage === 'undefined') return '';
  try {
    const value = sessionStorage.getItem(storageKey(productId));
    return value === 'GLOBAL' || value === 'PRODUCT' ? value : '';
  } catch {
    return '';
  }
}

function writeStoredFocus(productId: string, mode: AgentFocusMode) {
  if (!productId || typeof sessionStorage === 'undefined') return;
  try {
    sessionStorage.setItem(storageKey(productId), mode);
  } catch {
    /* ignore quota / private mode */
  }
}

function clearStoredFocus() {
  if (typeof sessionStorage === 'undefined') return;
  try {
    const keys = Object.keys(sessionStorage).filter((key) => key.startsWith(FOCUS_STORAGE_PREFIX));
    for (const key of keys) sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export function resetAgentFocus() {
  focusMode.value = 'GLOBAL';
  focusPinned.value = false;
  clearStoredFocus();
}

export function useAgentFocus() {
  const route = useRoute();
  const panel = usePcAgentPanelStore();
  const auth = useAuthStore();

  const productId = computed(() => {
    if (typeof route.params.productId === 'string' && route.params.productId) return route.params.productId;
    if (typeof route.query.product === 'string' && route.query.product) return route.query.product;
    return panel.productId || '';
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
    const stored = readStoredFocus(id);
    if (stored) {
      focusMode.value = stored;
      focusPinned.value = stored === 'GLOBAL';
      return;
    }
    if (prev && id !== prev) {
      focusPinned.value = false;
      focusMode.value = 'PRODUCT';
      writeStoredFocus(id, 'PRODUCT');
      return;
    }
    if (!focusPinned.value) {
      focusMode.value = 'PRODUCT';
      writeStoredFocus(id, 'PRODUCT');
    }
  }, { immediate: true });

  function setGlobal() {
    focusMode.value = 'GLOBAL';
    focusPinned.value = true;
    if (productId.value) writeStoredFocus(productId.value, 'GLOBAL');
  }

  function setProduct() {
    if (productId.value) {
      focusMode.value = 'PRODUCT';
      focusPinned.value = true;
      writeStoredFocus(productId.value, 'PRODUCT');
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
