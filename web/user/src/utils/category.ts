
export function isDemoCategoryId(id: unknown): boolean {
  const value = String(id ?? '').trim();
  if (!value) return true;
  if (value.startsWith('S')) return true;
  if (/^9[0-2]/.test(value)) return true;
  return /^\d{1,3}$/.test(value);
}

export function categoryPreferenceScore(id: unknown, childCount = 0): number {
  const value = String(id ?? '');
  let score = 0;
  if (value.startsWith('S')) score += 300;
  if (/^9[0-2]/.test(value)) score += 200;
  else if (/^\d{1,3}$/.test(value)) score += 100;
  score -= Math.min(Number(childCount) || 0, 50) * 10;
  return score;
}

export function normalizeCategoryTree(data: unknown): any[] {
  if (!Array.isArray(data) || !data.length) return [];

  const hasNestedChildren = data.some((item) => Array.isArray(item?.children));
  if (hasNestedChildren) {
    return data.filter((item) => !item.pCategoryId || item.pCategoryId === '0');
  }

  const list = data as any[];
  const roots = list.filter((c) => !c.pCategoryId || c.pCategoryId === '0');
  return roots.map((root) => ({
    ...root,
    children: list.filter((c) => c.pCategoryId === root.categoryId)
  }));
}

export function countCategoryNodes(roots: any[]): number {
  let n = 0;
  const walk = (items: any[]) => {
    items.forEach((item) => {
      n += 1;
      if (item.children?.length) walk(item.children);
    });
  };
  walk(roots);
  return n;
}

export function findCategoryInTree(roots: any[], categoryId: string): any | null {
  for (const root of roots) {
    if (String(root.categoryId) === String(categoryId)) return root;
    for (const child of root.children || []) {
      if (String(child.categoryId) === String(categoryId)) return child;
    }
  }
  return null;
}

export function findParentCategory(roots: any[], categoryId: string): any | null {
  for (const root of roots) {
    if (root.children?.some((c: any) => String(c.categoryId) === String(categoryId))) {
      return root;
    }
  }
  return null;
}

export type FlattenCategoryLabelMode = 'child' | 'full';

export function dedupeCategoryTree(roots: any[]): any[] {
  const pick = (items: any[]): any[] => {
    const groups = new Map<string, any[]>();
    const order: string[] = [];
    for (const item of items || []) {
      const name = String(item?.categoryName || '').trim();
      if (!name || !item?.categoryId) continue;
      if (!groups.has(name)) {
        groups.set(name, []);
        order.push(name);
      }
      groups.get(name)!.push(item);
    }
    return order.map((name) => {
      const group = groups.get(name)!;
      group.sort((left, right) => (
        categoryPreferenceScore(left.categoryId, left.children?.length)
        - categoryPreferenceScore(right.categoryId, right.children?.length)
      ));
      const best = group[0];
      const mergedChildren = group.flatMap((node) => (Array.isArray(node.children) ? node.children : []));
      return {
        ...best,
        children: mergedChildren.length ? pick(mergedChildren) : []
      };
    });
  };
  return pick(Array.isArray(roots) ? roots : []);
}

export function storefrontCategoryTree(data: unknown): any[] {
  const prune = (nodes: any[]): any[] => nodes
    .map((node) => ({ ...node, children: prune(node.children || []) }))
    .filter((node) => (node.children?.length) || !isDemoCategoryId(node.categoryId));
  return prune(dedupeCategoryTree(normalizeCategoryTree(data)));
}

export function flattenCategoryOptions(
  roots: any[],
  labelMode: FlattenCategoryLabelMode = 'full'
): { categoryId: string; categoryName: string }[] {
  const out: { categoryId: string; categoryName: string }[] = [];
  roots.forEach((root) => {
    if (root.children?.length) {
      root.children.forEach((sub: any) => {
        out.push({
          categoryId: sub.categoryId,
          categoryName:
            labelMode === 'child' ? sub.categoryName : `${root.categoryName} / ${sub.categoryName}`
        });
      });
    } else {
      out.push({ categoryId: root.categoryId, categoryName: root.categoryName });
    }
  });
  return out;
}
