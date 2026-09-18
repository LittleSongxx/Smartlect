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
