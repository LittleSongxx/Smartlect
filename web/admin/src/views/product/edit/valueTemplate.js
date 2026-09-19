// 新建属性值行的唯一模板来源：三处创建点（ProductBase 分类模板种子、
// ProductSkuProperty 手动加行/默认行）必须字段一致，否则图集等编辑区会静默丢槽位。
export function createPropertyValue(slotCount = 5, index = 0) {
  return {
    propertyValueId: `${Date.now()}${index}`,
    propertyCover: '',
    propertyGalleryArray: Array(slotCount).fill(''),
    propertyValue: '',
    propertyRemark: '',
  }
}
