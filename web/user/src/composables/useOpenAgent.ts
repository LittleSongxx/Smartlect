import { useRouter } from 'vue-router';
import { useDevice } from '@/composables/useDevice';
import { useAuthStore } from '@/stores/auth';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';
import {
  saveAgentConsultProduct,
  type AgentConsultProduct
} from '@/utils/agentProductConsult';

export function useOpenAgent() {
  const router = useRouter();
  const authStore = useAuthStore();
  const { isDesktop } = useDevice();
  const pcAgentPanel = usePcAgentPanelStore();

  const openAgent = (options?: {
    consultProduct?: AgentConsultProduct | null;
    fromProduct?: boolean;
    presetMessage?: string;
    draft?: string;
    productId?: string;
    skuKey?: string;
  }) => {
    const productId = options?.productId || options?.consultProduct?.productId || '';
    const skuKey = options?.skuKey || '';
    const draft = options?.draft || options?.presetMessage || '';
    const fromProduct = !!options?.fromProduct || !!productId;
    if (options?.consultProduct?.productId) {
      saveAgentConsultProduct(options.consultProduct, authStore.userInfo?.userId as string | undefined);
    }

    if (isDesktop.value) {
      pcAgentPanel.open({
        fromProduct,
        draft,
        productId: productId ? String(productId) : '',
        skuKey: skuKey ? String(skuKey) : ''
      });
      return;
    }

    const query: Record<string, string> = {};
    if (productId) query.product = String(productId);
    if (skuKey) query.sku = String(skuKey);
    if (draft) query.draft = draft.slice(0, 8000);
    if (fromProduct) query.fromProduct = '1';
    router.push({ path: '/assistant', query: Object.keys(query).length ? query : undefined });
  };

  return { openAgent };
}
