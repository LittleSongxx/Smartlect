// 列表类页面（分类、搜索、全部商品）共用的查询参数规整：
// 手改链接里的价格/排序不能原样转给 Java，必须在客户端先判掉。
export class ProductQueryError extends Error {}

const PRICE_PATTERN = /^\d+(\.\d{1,2})?$/;
const MAX_PRICE = 1000000;
const SORT_KEYS = ['PRICE', 'SALE'];
const SORT_DIRECTIONS = ['ASC', 'DESC'];

/** 价格入参：空值返回 undefined；格式与上限不合格直接抛错（不发给服务端）。 */
export function normalizePrice(value: unknown, label = '价格'): string | undefined {
  const trimmed = String(value ?? '').trim();
  if (!trimmed) return undefined;
  if (!PRICE_PATTERN.test(trimmed)) {
    throw new ProductQueryError(`${label}需为非负金额，最多两位小数。`);
  }
  if (Number(trimmed) > MAX_PRICE) {
    throw new ProductQueryError(`${label}超出有效范围。`);
  }
  return trimmed;
}

/** 校验价格区间：任一无效即抛错，最低价高于最高价也抛错。 */
export function normalizePriceRange(
  from: unknown,
  to: unknown,
  label = '价格'
): { priceFrom?: string; priceTo?: string } {
  const priceFrom = normalizePrice(from, label);
  const priceTo = normalizePrice(to, label);
  if (priceFrom !== undefined && priceTo !== undefined && Number(priceFrom) > Number(priceTo)) {
    throw new ProductQueryError('最低价不能高于最高价。');
  }
  return { priceFrom, priceTo };
}

/**
 * 排序入参：接受 `KEY:DIRECTION`（如 `PRICE:ASC`）与 `SALE`；
 * 非白名单值抛错，空值返回空对象。
 */
export function normalizeSort(value: unknown): { sortKey?: string; sortDirection?: string } {
  const trimmed = String(value ?? '').trim();
  if (!trimmed) return {};
  const [key, direction = ''] = trimmed.split(':');
  if (!SORT_KEYS.includes(key)) throw new ProductQueryError('排序方式无效。');
  if (direction && !SORT_DIRECTIONS.includes(direction)) throw new ProductQueryError('排序方式无效。');
  return direction ? { sortKey: key, sortDirection: direction } : { sortKey: key };
}
