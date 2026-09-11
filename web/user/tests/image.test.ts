import { describe, expect, it } from 'vitest';
import { resolveImageUrl } from '../src/utils/image';
import { pickDefaultSku } from '../src/utils/product';

describe('商品图地址与规格预选', () => {
  it('已是货架资源路径不再套一层，原始路径编码 sourceName', () => {
    const ready = '/api/file/getResource?sourceName=2026-06/cover.png';
    expect(resolveImageUrl(ready)).toBe(ready);
    expect(resolveImageUrl('2026-06/a b.png')).toBe(
      '/api/file/getResource?sourceName=' + encodeURIComponent('2026-06/a b.png')
    );
    expect(resolveImageUrl('https://cdn.example/x.png')).toBe('https://cdn.example/x.png');
  });

  it('详情按 query.sku 预选规格', () => {
    const skus = [
      { propertyValueIds: 'a', stock: 3 },
      { propertyValueIds: 'b', stock: 9 },
    ];
    expect(pickDefaultSku(skus, 'b')?.propertyValueIds).toBe('b');
    expect(pickDefaultSku(skus)?.propertyValueIds).toBe('a');
  });
});
