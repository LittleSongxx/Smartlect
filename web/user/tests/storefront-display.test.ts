import { describe, expect, it } from 'vitest';
import { storefrontCategoryTree } from '../src/utils/category';
import { filterStorefrontProducts, isShelfFillerProduct } from '../src/utils/product';
import { isAllowedProductImageSrc, normalizeProductDesc } from '../src/utils/productDesc';

describe('店面分类与假货过滤', () => {
  it('同名分类保留真实货架并丢掉空的合成根类', () => {
    const tree = storefrontCategoryTree([
      { categoryId: '90', categoryName: '数码', pCategoryId: '0' },
      { categoryId: '10001', categoryName: '数码家电', pCategoryId: '0' },
      { categoryId: '20001', categoryName: '手机通讯', pCategoryId: '10001' },
      { categoryId: '91', categoryName: '家居', pCategoryId: '0' },
      { categoryId: 'S91', categoryName: '家居', pCategoryId: '0' },
      { categoryId: '92', categoryName: '运动', pCategoryId: '0' },
      { categoryId: '10002', categoryName: '服装鞋帽', pCategoryId: '0' },
      { categoryId: '20009', categoryName: '运动户外', pCategoryId: '10002' },
    ]);
    expect(tree.map((row) => row.categoryName)).toEqual(['数码家电', '服装鞋帽']);
    expect(tree[0].children.map((row: { categoryName: string }) => row.categoryName)).toEqual(['手机通讯']);
    expect(tree[1].children.map((row: { categoryName: string }) => row.categoryName)).toEqual(['运动户外']);
  });

  it('同名根类优先真实 ID，并合并子类', () => {
    const tree = storefrontCategoryTree([
      { categoryId: '90', categoryName: '数码', pCategoryId: '0' },
      { categoryId: '10001', categoryName: '数码', pCategoryId: '0' },
      { categoryId: '901', categoryName: '空子类', pCategoryId: '90' },
      { categoryId: '20003', categoryName: '数码影音', pCategoryId: '10001' },
    ]);
    expect(tree).toHaveLength(1);
    expect(tree[0].categoryId).toBe('10001');
    expect(tree[0].children.map((row: { categoryId: string }) => row.categoryId)).toEqual(['20003']);
  });

  it('首页不展示 91 合成货和 Smartlect 占位标题', () => {
    expect(isShelfFillerProduct({ productId: '910000000000001', productName: '席梦思床垫' })).toBe(true);
    expect(isShelfFillerProduct({ productId: '622491960431656', productName: '旺旺雪饼' })).toBe(false);
    expect(isShelfFillerProduct({ productId: '10001', productName: 'Smartlect家居1' })).toBe(true);
    expect(filterStorefrontProducts([
      { productId: '910000000000001', productName: '合成货', status: 1 },
      { productId: '622491960431656', productName: '真货', status: 1 },
    ]).map((row) => row.productId)).toEqual(['622491960431656']);
  });

  it('详情只渲染本地货架图，助手路径继续拒绝外链', () => {
    const desc = normalizeProductDesc('![](/api/file/getResource?sourceName=2026-06/cover.png)');
    expect(desc).toContain('/api/file/getResource?sourceName=2026-06/cover.png');
    expect(isAllowedProductImageSrc('/api/file/getResource?sourceName=2026-06/cover.png')).toBe(true);
    expect(isAllowedProductImageSrc('https://evil.example/x.png')).toBe(false);
    expect(isAllowedProductImageSrc('/api/file/getResource?sourceName=../secret')).toBe(false);
  });
});
