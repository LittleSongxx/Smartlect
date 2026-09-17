import { aiGet } from '@/api/client';
import { isIsolatedProductId } from '@/utils/product';

export type ProductScope = { include: string[] | null; exclude: string[] };

const empty: ProductScope = { include: null, exclude: [] };
let cached: { owner: string; scope: ProductScope } | null = null;

export function clearProductScopeCache() {
  cached = null;
}

export function inProductScope(productId: string, scope: ProductScope | null | undefined): boolean {
  if (!productId || !scope) return true;
  if (scope.exclude.includes(productId)) return false;
  if (scope.include == null) return !isIsolatedProductId(productId);
  return scope.include.includes(productId);
}

export function excludeProductIds(scope: ProductScope | null | undefined): string {
  return (scope?.exclude || []).join(',');
}

export async function loadProductScope(owner: string): Promise<ProductScope> {
  if (!owner) return empty;
  if (cached?.owner === owner) return cached.scope;
  try {
    const data = await aiGet<ProductScope>('/catalog/scope');
    const scope: ProductScope = {
      include: Array.isArray(data?.include) ? data.include.filter((id) => typeof id === 'string' && id) : null,
      exclude: Array.isArray(data?.exclude) ? data.exclude.filter((id) => typeof id === 'string' && id) : [],
    };
    cached = { owner, scope };
    return scope;
  } catch {
    return empty;
  }
}
