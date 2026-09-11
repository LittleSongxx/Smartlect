import type { Promotion } from '@/api/traffic';

export type HomeTile = Record<string, any> & {
  kind?: 'ad' | 'hot';
  promotion?: Promotion;
};

export function productFromPromotion(item: Promotion): HomeTile {
  const yuan = item.price_cents != null ? Number(item.price_cents) / 100 : undefined;
  return {
    kind: 'ad',
    productId: item.productId,
    productName: item.productName,
    cover: item.cover,
    minPrice: yuan,
    price: yuan,
    propertyValueIds: item.propertyValueIds,
    promotion: item
  };
}

export function mixHomeAds(
  hotProducts: any[],
  ads: Promotion[],
  maxAds = 2,
  maxTiles = 5
): HomeTile[] {
  const seen = new Set<string>();
  const tiles: HomeTile[] = [];
  for (const ad of ads.slice(0, maxAds)) {
    const id = String(ad.productId || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    tiles.push(productFromPromotion(ad));
  }
  for (const product of hotProducts || []) {
    const id = String(product?.productId || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    tiles.push({ kind: 'hot', ...product });
    if (tiles.length >= maxTiles) break;
  }
  return tiles;
}
