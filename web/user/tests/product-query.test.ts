import { describe, expect, it } from 'vitest';
import { ProductQueryError, normalizePrice, normalizePriceRange, normalizeSort } from '../src/utils/productQuery';

describe('列表查询参数规整', () => {
  it('价格只接受非负金额、最多两位小数', () => {
    expect(normalizePrice(' 12.50 ')).toBe('12.50');
    expect(normalizePrice('')).toBeUndefined();
    expect(normalizePrice(undefined)).toBeUndefined();
    expect(() => normalizePrice('abc')).toThrow(ProductQueryError);
    expect(() => normalizePrice('12.345')).toThrow('价格需为非负金额，最多两位小数。');
    expect(() => normalizePrice('-1')).toThrow(ProductQueryError);
    expect(() => normalizePrice('1000001')).toThrow('价格超出有效范围。');
  });

  it('价格区间校验顺序与大小关系', () => {
    expect(normalizePriceRange('30', '90')).toEqual({ priceFrom: '30', priceTo: '90' });
    expect(normalizePriceRange('', '')).toEqual({ priceFrom: undefined, priceTo: undefined });
    expect(() => normalizePriceRange('abc', '')).toThrow(ProductQueryError);
    expect(() => normalizePriceRange('90', '30')).toThrow('最低价不能高于最高价。');
  });

  it('排序只放行白名单', () => {
    expect(normalizeSort('PRICE:ASC')).toEqual({ sortKey: 'PRICE', sortDirection: 'ASC' });
    expect(normalizeSort('SALE')).toEqual({ sortKey: 'SALE' });
    expect(normalizeSort('')).toEqual({});
    expect(() => normalizeSort('DROP:TABLE')).toThrow('排序方式无效。');
    expect(() => normalizeSort('PRICE:SIDEWAYS')).toThrow('排序方式无效。');
  });
});
