import { describe, expect, it } from 'vitest';
import { resolveValueGallery } from '../src/utils/productGallery';

// 图集解析的契约：属性值配了 propertyGallery 就整组切换，否则回退商品级 cover。
// 这是「选颜色换整组图」的唯一数据入口，锁住优先级和回退语义。

const props = (overrides: Record<string, any> = {}) => [
  {
    propertyId: '1001',
    propertyName: '颜色',
    propertyValues: [
      { propertyValueId: 'v1', propertyValue: '星夜银', propertyCover: '2026-06/silver.jpg', ...overrides.v1 },
      { propertyValueId: 'v2', propertyValue: '冷夜蓝', propertyCover: '2026-06/blue.jpg', ...overrides.v2 }
    ]
  },
  {
    propertyId: '2002',
    propertyName: '存储容量',
    propertyValues: [
      { propertyValueId: 's1', propertyValue: '12+512G', ...overrides.s1 }
    ]
  }
];

describe('详情页图集解析', () => {
  it('选中值配置了图集时整组返回', () => {
    const list = props({ v2: { propertyGallery: '2026-06/blue.jpg,2026-06/blue-back.jpg' } });
    expect(resolveValueGallery(list, { 1001: 'v2', 2002: 's1' }, 'p1.jpg,p2.jpg')).toEqual([
      '2026-06/blue.jpg',
      '2026-06/blue-back.jpg'
    ]);
  });

  it('未配置图集时回退商品级 cover（当前行为）', () => {
    expect(resolveValueGallery(props(), { 1001: 'v2', 2002: 's1' }, 'p1.jpg,p2.jpg,p3.jpg')).toEqual([
      'p1.jpg',
      'p2.jpg',
      'p3.jpg'
    ]);
  });

  it('图集为空串/空白项时视为未配置并回退', () => {
    const list = props({ v1: { propertyGallery: ' , ' } });
    expect(resolveValueGallery(list, { 1001: 'v1' }, 'p1.jpg')).toEqual(['p1.jpg']);
  });

  it('多个属性都配置时取属性顺序里第一个命中的', () => {
    const list = props({ s1: { propertyGallery: '2026-06/cap.jpg' }, v2: { propertyGallery: '2026-06/blue.jpg' } });
    expect(resolveValueGallery(list, { 1001: 'v2', 2002: 's1' }, '')).toEqual(['2026-06/blue.jpg']);
  });

  it('部分选中的属性值不存在时跳过并回退', () => {
    expect(resolveValueGallery(props(), {}, 'p1.jpg')).toEqual(['p1.jpg']);
    expect(resolveValueGallery(null, null, 'p1.jpg')).toEqual(['p1.jpg']);
    expect(resolveValueGallery(props(), { 1001: 'v1' }, undefined)).toEqual([]);
  });
});
