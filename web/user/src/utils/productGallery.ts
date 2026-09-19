import { splitImagePaths } from '@/utils/image';

/**
 * 详情页图集解析：SKU 属性值配置了图集（propertyGallery）就用它的，
 * 否则回退商品级 cover。属性按 productPropertyList 顺序取第一个命中的。
 */
export function resolveValueGallery(
  productPropertyList: any[] | null | undefined,
  selectedProperty: Record<string, string> | null | undefined,
  productCover: unknown
): string[] {
  for (const prop of productPropertyList || []) {
    const valId = selectedProperty?.[prop.propertyId];
    const val = prop.propertyValues?.find((v: any) => v.propertyValueId === valId);
    const gallery = splitImagePaths(val?.propertyGallery);
    if (gallery.length) return gallery;
  }
  return splitImagePaths(typeof productCover === 'string' ? productCover : '');
}

/**
 * 结算/弹层头图口径，与订单快照同规则：已选属性值里第一个非空封面，
 * 否则商品级 cover 首图。详情页 buyNow 与加购弹层共用，避免两处口径漂移。
 */
export function pickSkuCover(
  productPropertyList: any[] | null | undefined,
  selectedProperty: Record<string, string> | null | undefined,
  productCover: unknown
): string {
  for (const prop of productPropertyList || []) {
    const valId = selectedProperty?.[prop.propertyId];
    const val = prop.propertyValues?.find((v: any) => v.propertyValueId === valId);
    const cover = String(val?.propertyCover || '').trim();
    if (cover) return cover;
  }
  if (typeof productCover !== 'string') return '';
  return splitImagePaths(productCover)[0] || '';
}
