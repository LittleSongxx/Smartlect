import { defineStore } from 'pinia';
import { ref } from 'vue';

export const usePcAgentPanelStore = defineStore('pcAgentPanel', () => {
  const visible = ref(false);
  const fromProduct = ref(false);
  const draft = ref('');
  const productId = ref('');
  const skuKey = ref('');

  function open(options?: {
    fromProduct?: boolean;
    draft?: string;
    productId?: string;
    skuKey?: string;
  }) {
    fromProduct.value = !!options?.fromProduct;
    draft.value = options?.draft?.slice(0, 8000) || '';
    productId.value = options?.productId ? String(options.productId) : '';
    skuKey.value = options?.skuKey ? String(options.skuKey) : '';
    visible.value = true;
  }

  function close() {
    visible.value = false;
    fromProduct.value = false;
  }

  function toggle() {
    if (visible.value) close();
    else open();
  }

  function consumeFromProduct() {
    const v = fromProduct.value;
    fromProduct.value = false;
    return v;
  }

  return {
    visible,
    fromProduct,
    draft,
    productId,
    skuKey,
    open,
    close,
    toggle,
    consumeFromProduct
  };
});
