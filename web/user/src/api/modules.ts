import request from './http';
import { withCache } from '@/utils/apiCache';
import { loadSession, ownerKey, session } from '@/api/client';
import { excludeProductIds, loadProductScope } from '@/utils/productScope';

async function withProductScope(params: Record<string, unknown> = {}) {
  if (!session.value) {
    try { await loadSession(); } catch { /* visitor scope is best-effort */ }
  }
  const owner = session.value ? ownerKey(session.value.actor) : '';
  const scope = await loadProductScope(owner);
  const excluded = [excludeProductIds(scope), String(params.excludeProductIds || '')]
    .filter(Boolean)
    .join(',');
  return { ...params, excludeProductIds: excluded };
}

export { locationApi } from './location';
export type { LocationPayload, LocationWeatherPayload } from './location';

const CACHE_KEYS = {
  CATEGORY: 'product:category:v2',
  COMMEND: 'product:commend'
} as const;

const productDetailKey = (id: string) => `product:detail:${id}`;

export const accountApi = {
  checkCode: () => request.get('/account/checkCode'),
  login: (params: Record<string, unknown>) => request.postForm('/account/login', params),
  register: (params: Record<string, unknown>) => request.postForm('/account/register', params),
  autoLogin: () => request.get('/account/autoLogin'),
  logout: () => request.postForm('/account/logout'),
  getUserInfo: () => request.get('/account/getUserInfo'),
  updateUserInfo: (params: Record<string, unknown>) => request.postForm('/account/updateUserInfo', params),
  updatePassword: (params: Record<string, unknown>) => request.postForm('/account/updatePassword', params),
  getEmailCode: (params: Record<string, unknown>) => request.postForm('/account/getEmailCode', params),
  forgetPassword: (params: Record<string, unknown>) => request.postForm('/account/forgetPassword', params)
};

const RECENT_KEY = 'smartlect:recent-keywords';

function readRecentKeywords(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string' && item) : [];
  } catch {
    return [];
  }
}

function writeRecentKeywords(values: string[]) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(values.slice(0, 20)));
}

export const searchApi = {
  loadHotKeywords: async () => [] as string[],
  loadRecentKeywords: async () => readRecentKeywords(),
  saveKeyword: async (keyword: string) => {
    const next = [keyword.trim(), ...readRecentKeywords().filter((item) => item !== keyword.trim())].filter(Boolean);
    writeRecentKeywords(next);
  },
  clearRecentKeywords: async () => writeRecentKeywords([]),
  removeRecentKeyword: async (keyword: string) => {
    writeRecentKeywords(readRecentKeywords().filter((item) => item !== keyword));
  },
  loadGuessKeywords: async () => [] as string[],
  loadRecommendProducts: async (limit = 8) => {
    try {
      const list = await productApi.loadCommendProduct();
      return Array.isArray(list) ? list.slice(0, limit) : [];
    } catch {
      return [];
    }
  }
};

export const productApi = {

  loadCategory: () =>
    withCache(() => request.get('/product/loadCategory'), {
      key: CACHE_KEYS.CATEGORY,
      ttl: 30 * 60 * 1000
    }),

  loadCommendProduct: () =>
    withCache(() => request.get('/product/loadCommendProduct'), {
      key: CACHE_KEYS.COMMEND,
      ttl: 5 * 60 * 1000
    }),
  loadProduct: async (params: Record<string, unknown>) =>
    request.postForm('/product/loadProduct', await withProductScope(params)),

  getProduct: (productId: string) =>
    withCache(() => request.postForm('/product/getProduct', { productId }), {
      key: productDetailKey(productId),
      ttl: 2 * 60 * 1000
    }),
  searchProducts: async (params: Record<string, unknown>) =>
    request.postForm('/product/loadProduct', await withProductScope({
      pageNo: params.pageNo || 1,
      keyword: String(params.keyWords || params.keyword || '').slice(0, 50),
      categoryId: params.categoryId || '',
      priceFrom: params.priceFrom || '',
      priceTo: params.priceTo || '',
      sortKey: params.sortKey || '',
      sortDirection: params.sortDirection || ''
    }))
};

export const cartApi = {
  add2Cart: (params: Record<string, unknown>) => request.postForm('/productCart/add2Cart', params),
  loadProductCart: (params: Record<string, unknown>) => request.postForm('/productCart/loadProductCart', params),
  deleteCart: (cartId: string) => request.postForm('/productCart/deleteCart', { cartId })
};

export const orderApi = {
  postOrder: (payload: Record<string, unknown>, idempotencyKey: string) =>
    request.post('/order/postOrder', payload, {
      headers: { 'Idempotency-Key': idempotencyKey }
    }),
  getPayInfo: (orderId: string) => request.postForm('/order/getPayInfo', { orderId }),
  getOrderInfo: (payOrderId: string) => request.postForm('/order/getOrderInfo', { payOrderId }),
  loadMyOrder: (params: Record<string, unknown>) => request.postForm('/order/loadMyOrder', params),
  cancelOrder: (orderId: string) => request.postForm('/order/cancelOrder', { orderId }),
  deleteOrder: (orderId: string) => request.postForm('/order/deleteOrder', { orderId }),
  confirmOrder: (orderId: string) => request.postForm('/order/confirmOrder', { orderId }),
  getMyOrderDetail: (orderId: string) => request.postForm('/order/getMyOrderDetail', { orderId }),
  getLogistics: (orderId: string) => request.postForm('/order/getLogistics', { orderId }),
  getOrderCountInfo: () => request.get('/order/getOrderCountInfo'),
  refundOrder: (orderItemId: string) => request.postForm('/order/refundOrder', { orderItemId })
};

export const addressApi = {
  loadDataList: () => request.get('/userAddress/loadDataList'),
  addAddress: (params: Record<string, unknown>) => request.postForm('/userAddress/addAddress', params),
  updateAddress: (params: Record<string, unknown>) => request.postForm('/userAddress/updateAddress', params),
  delAddress: (addressId: string) => request.postForm('/userAddress/delAddress', { addressId }),
  updateDefault: (addressId: string) => request.postForm('/userAddress/updateDefault', { addressId })
};

export const couponApi = {
  loadDiscountCoupon: (params: Record<string, unknown>) =>
    request.postForm('/discountCoupon/loadDiscountCoupon', params),
  rushCoupon: (couponId: string, idempotencyKey: string) =>
    request.postForm(
      '/discountCoupon/rushCoupon',
      { couponId },
      { headers: { 'Idempotency-Key': idempotencyKey } }
    ),
  buyDiscountCoupon: (couponId: string, payMethod: string, idempotencyKey: string) =>
    request.postForm(
      '/discountCoupon/buyDiscountCoupon',
      { couponId, payMethod },
      { headers: { 'Idempotency-Key': idempotencyKey } }
    ),
  loadUserCoupon: (params: Record<string, unknown>) =>
    request.postForm('/discountCoupon/loadUserCoupon', params),
  getDiscountCouponDetail: (couponId: string) =>
    request.postForm('/discountCoupon/getDiscountCouponDetail', { couponId })
};

export const payTradeApi = {
  loadMyTrades: (pageNo: number) => request.postForm('/payTrade/loadMyTrades', { pageNo })
};

export interface ImageUploadResult {
  path: string;
  contentSha256?: string;
  mimeType?: string;
  width?: number;
  height?: number;
  expiresAt?: string;
  pendingReview?: boolean;
  moderationId?: number;
  moderationStatus?: string;
  scene?: string;
}

export interface ImageUploadOptions {

  skipPrepare?: boolean;
}

export const fileApi = {
  uploadImage: async (
    file: Blob,
    createThumbnail = true,
    scene?: 'avatar',
    orderId?: string,
    options?: ImageUploadOptions
  ): Promise<ImageUploadResult> => {
    const { prepareForUpload } = await import('@/utils/imageUpload');
    const prepared = options?.skipPrepare ? file : await prepareForUpload(file);
    if (!prepared || prepared.size < 1024) {
      throw new Error('图片导出失败，请重试');
    }
    const ext = prepared.type === 'image/png' ? 'png' : 'jpg';
    const formData = new FormData();
    formData.append('file', prepared, file instanceof File ? file.name.replace(/\.\w+$/, `.${ext}`) : `image.${ext}`);
    formData.append('createThumbnail', String(createThumbnail));
    if (scene) formData.append('scene', scene);
    if (orderId) formData.append('orderId', orderId);
    const response = await fetch('/api/file/uploadImage', {
      method: 'POST',
      body: formData,
      credentials: 'include'
    });
    const result = await response.json();
    if (result.code !== 200) {
      const { ApiBusinessError } = await import('@/utils/apiError');
      const payload = result.data || {};
      throw new ApiBusinessError(result.info || '上传失败', {
        code: result.code,
        errorType: payload.errorType,
        unbanAt: payload.unbanAt
      });
    }
    const data = result.data;
    const { extractUploadPath } = await import('@/utils/image');
    const path = extractUploadPath(data) || '';
    const pendingReview =
      typeof data === 'object' && data !== null && 'pendingReview' in data
        ? !!(data as { pendingReview?: boolean }).pendingReview
        : false;
    const moderationId =
      typeof data === 'object' && data !== null && (data as { moderationId?: unknown }).moderationId != null
        ? Number((data as { moderationId?: unknown }).moderationId)
        : undefined;
    const moderationStatus =
      typeof data === 'object' && data !== null && (data as { moderationStatus?: unknown }).moderationStatus
        ? String((data as { moderationStatus?: unknown }).moderationStatus)
        : undefined;
    const sceneValue =
      typeof data === 'object' && data !== null && (data as { scene?: unknown }).scene
        ? String((data as { scene?: unknown }).scene)
        : undefined;
    const contentSha256 =
      typeof data === 'object' && data !== null && (data as { contentSha256?: unknown }).contentSha256
        ? String((data as { contentSha256?: unknown }).contentSha256)
        : undefined;
    const mimeType =
      typeof data === 'object' && data !== null && (data as { mimeType?: unknown }).mimeType
        ? String((data as { mimeType?: unknown }).mimeType)
        : undefined;
    const width =
      typeof data === 'object' && data !== null && Number.isFinite(Number((data as { width?: unknown }).width))
        ? Number((data as { width?: unknown }).width)
        : undefined;
    const height =
      typeof data === 'object' && data !== null && Number.isFinite(Number((data as { height?: unknown }).height))
        ? Number((data as { height?: unknown }).height)
        : undefined;
    const expiresAt =
      typeof data === 'object' && data !== null && (data as { expiresAt?: unknown }).expiresAt
        ? String((data as { expiresAt?: unknown }).expiresAt)
        : undefined;
    return {
      path,
      contentSha256,
      mimeType,
      width,
      height,
      expiresAt,
      pendingReview,
      moderationId: Number.isFinite(moderationId) ? moderationId : undefined,
      moderationStatus,
      scene: sceneValue
    };
  }
};

