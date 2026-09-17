import { isProductOnSale as isOnSale } from '@/constants/backendEnums';

export { isProductOnSale } from '@/constants/backendEnums';

export function isIsolatedProductId(productId: string | null | undefined): boolean {
  const id = String(productId ?? '');
  return /^(9100|9300)/.test(id);
}

export function isShelfFillerProduct(product: { productId?: string; productName?: string } | null | undefined): boolean {
  if (isIsolatedProductId(product?.productId)) return true;
  const name = String(product?.productName ?? '').trim();
  return /^Smartlect(数码|家居|运动|阅读|数码家电)/.test(name);
}

export function filterOnSaleProducts<T extends { status?: number | null; productId?: string }>(list: T[] | null | undefined): T[] {
  return (list || []).filter((item) => isOnSale(item));
}

export function filterStorefrontProducts<T extends { status?: number | null; productId?: string; productName?: string }>(
  list: T[] | null | undefined
): T[] {
  return filterOnSaleProducts(list).filter((item) => !isShelfFillerProduct(item));
}

export function splitStorefrontPage<T extends { status?: number | null; productId?: string; productName?: string }>(
  list: T[] | null | undefined
): { visible: T[]; fetched: number } {
  const onSale = filterOnSaleProducts(list);
  return {
    visible: onSale.filter((item) => !isShelfFillerProduct(item)),
    fetched: onSale.length
  };
}

export function pickDefaultSku<T extends { stock?: number | null; propertyValueIds?: string }>(
  skuList: T[],
  preferredIds?: string | null
): T | null {
  if (!skuList.length) return null;
  if (preferredIds) {
    const match = skuList.find((sku) => sku.propertyValueIds === preferredIds);
    if (match) return match;
  }
  return skuList.find((sku) => Number(sku.stock) > 0) ?? skuList[0];
}
