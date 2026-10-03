export type HomeTile = Record<string, any> & {
  kind?: 'recommend' | 'hot';
};

export function recommendationProductPath(item: Record<string, any>) {
  const sku = item.propertyValueIds ? `?sku=${encodeURIComponent(String(item.propertyValueIds))}` : '';
  return `/product/${item.productId}${sku}`;
}

/**
 * 首页混排：确定性精选（Java commend 商品）在前、热销补充，
 * 同一商品去重，最多 maxTiles 个。
 */
export function mixHomeRecommendations(
  hotProducts: any[],
  recommended: Record<string, any>[],
  maxRecommended = 4,
  maxTiles = 5
): HomeTile[] {
  const seen = new Set<string>();
  const tiles: HomeTile[] = [];
  for (const item of recommended.slice(0, maxRecommended)) {
    const id = String(item.productId || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    tiles.push({ kind: 'recommend', ...item });
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
