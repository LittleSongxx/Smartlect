// 商品编辑页属性值图集的三段纯逻辑：回显填充 / 提交 join / 色卡兜底。
// 从 ProductEdit.vue 抽出以便测试（回显↔提交必须互逆，兜底保证订单快照有图）。

// 回显：propertyGallery 逗号串 → 固定槽位数组（不足补空位，超长不截断）
export function toGallerySlots(propertyGallery, slotCount) {
  const gallery = String(propertyGallery || '').split(',').filter(Boolean)
  return [...gallery, ...Array(Math.max(0, slotCount - gallery.length)).fill('')]
}

// 提交：槽位数组 → 逗号串（与 toGallerySlots 互逆）
export function joinGallerySlots(propertyGalleryArray) {
  return (propertyGalleryArray || []).filter(Boolean).join(',')
}

// 色卡兜底：coverType=1 且色卡为空而图集非空时，取图集首张
// 返回新的 value 对象，不改写入参
export function fillCoverDefault(value, coverType) {
  const gallery = joinGallerySlots(value?.propertyGalleryArray)
  if (coverType !== 1 || value?.propertyCover || !gallery) return value
  return { ...value, propertyCover: gallery.split(',')[0] }
}

// 回显整表：给每个属性值补 propertyGalleryArray 槽位与空色卡默认值
export function normalizeValueGalleries(propertyList, slotCount) {
  return (propertyList || []).map((property) => ({
    ...property,
    propertyValues: (property.propertyValues || []).map((value) => ({
      ...value,
      propertyCover: value.propertyCover || '',
      propertyGalleryArray: toGallerySlots(value.propertyGallery, slotCount),
    })),
  }))
}
