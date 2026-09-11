import { categoryPreferenceScore } from '@/utils/category';

// Display only Java response fields. These labels never replace saved transaction parameters.
export function productName(detail: Record<string, any> | null | undefined, productId: string) {
  const product = detail?.productInfo;
  return product?.productId === productId && typeof product.productName === 'string' && product.productName.trim()
    ? product.productName.trim() : '商品名称待核对';
}

export function skuLabel(detail: Record<string, any> | null | undefined, propertyValueIds: string) {
  const names = new Map<string, string>();
  for (const property of Array.isArray(detail?.productPropertyList) ? detail.productPropertyList : []) {
    for (const value of Array.isArray(property?.propertyValues) ? property.propertyValues : []) {
      if (typeof value?.propertyValue === 'string' && value.propertyValue.trim()) {
        names.set(String(value.propertyValueId), value.propertyValue.trim());
      }
    }
  }
  const ids = propertyValueIds.split('-');
  return ids.length && ids.every((id) => id && names.has(id)) ? ids.map((id) => names.get(id)).join(' / ') : '规格名称待核对';
}

export function addressLabel(addresses: Record<string, any>[], addressId: string) {
  const address = addresses.find((item) => item.addressId === addressId);
  return typeof address?.addressee === 'string' && address.addressee.trim() && typeof address.address === 'string' && address.address.trim()
    ? `${address.addressee.trim()} · ${address.address.trim()}` : '收货信息待核对';
}

export function uniqueCategories<T extends { categoryId?: string; categoryName?: string }>(
  rows: T[] | null | undefined,
): T[] {
  const ranked = [...(rows || [])].filter((row) => row?.categoryId && row?.categoryName)
    .sort((left, right) => categoryPreferenceScore(left.categoryId) - categoryPreferenceScore(right.categoryId));
  const seen = new Set<string>();
  const unique: T[] = [];
  for (const row of ranked) {
    const name = row.categoryName!.trim();
    if (seen.has(name)) continue;
    seen.add(name);
    unique.push(row);
  }
  return unique;
}

export function coverUrl(source?: string | null): string {
  const raw = String(source ?? '').trim();
  if (!raw || raw.includes('..')) return '';
  if (raw.startsWith('/api/file/')) return raw;
  const first = raw.split(',')[0]?.trim() ?? '';
  if (!first || first.includes('..')) return '';
  return `/api/file/getResource?sourceName=${encodeURIComponent(first)}`;
}

export function stockCap(stock: unknown): number {
  if (stock === 0) return 0;
  if (typeof stock === 'number' && Number.isInteger(stock) && stock > 0) return Math.min(stock, 999);
  return 0;
}

export function canPurchase(options: {
  subjectType?: string;
  addressId?: string;
  selected?: { stock?: unknown } | null;
  quantity: unknown;
}): boolean {
  const cap = stockCap(options.selected?.stock);
  return options.subjectType === 'user'
    && Boolean(options.addressId)
    && Boolean(options.selected)
    && Number.isInteger(options.quantity)
    && Number(options.quantity) > 0
    && Number(options.quantity) <= 999
    && cap > 0
    && Number(options.quantity) <= cap;
}
