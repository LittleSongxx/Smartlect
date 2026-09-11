

export interface SmartlectCategoryNode {
  id?: string;
  cate_name?: string;
  pic?: string;
  children?: SmartlectCategoryNode[];
}

export interface EshopCategoryNode {
  categoryId: string;
  categoryName: string;
  children?: EshopCategoryNode[];
}


export function categoryToSmartlectShape(nodes: EshopCategoryNode[]): SmartlectCategoryNode[] {
  return nodes.map((n) => ({
    id: n.categoryId,
    cate_name: n.categoryName,
    pic: '',
    children: n.children?.length ? categoryToSmartlectShape(n.children) : []
  }));
}


export function productDisplayName(p: Record<string, unknown>): string {
  return String(p.productName ?? p.name ?? '');
}

export function productPriceText(p: Record<string, unknown>): string {
  const val = p.minPrice ?? p.price ?? p.salePrice;
  return val != null ? Number(val).toFixed(2) : '--';
}
