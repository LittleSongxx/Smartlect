import { recommendationTouch } from '@/api/traffic';

export type HomeTile = Record<string, any> & {
  kind?: 'recommend' | 'hot';
};

export function recommendationProductPath(item: Record<string, any>) {
  const sku = item.propertyValueIds ? `?sku=${encodeURIComponent(String(item.propertyValueIds))}` : '';
  return `/product/${item.productId}${sku}`;
}

export function productFromRecommendation(item: Record<string, any>): HomeTile {
  const yuan = item.price_cents != null ? Number(item.price_cents) / 100 : undefined;
  return {
    kind: 'recommend',
    productId: item.productId,
    productName: item.productName,
    cover: item.cover,
    minPrice: yuan ?? item.minPrice ?? item.price,
    price: yuan ?? item.price,
    propertyValueIds: item.propertyValueIds,
    sku_key: item.sku_key,
    recommendation_id: item.recommendation_id,
    position: item.position,
    reasons: item.reasons,
  };
}

export function mixHomeRecommendations(
  hotProducts: any[],
  recommended: Record<string, any>[],
  maxRecommended = 4,
  maxTiles = 5
): HomeTile[] {
  const seen = new Set<string>();
  const tiles: HomeTile[] = [];
  for (const item of recommended.slice(0, maxRecommended)) {
    if (!recommendationTouch(item)) continue;
    const id = String(item.productId || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    tiles.push(productFromRecommendation(item));
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
