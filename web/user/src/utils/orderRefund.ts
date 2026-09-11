const CLOSED_ORDER_STATUS = new Set([-1, 0, 4, 5, 6]);

export function yuanToCents(value: unknown): number {
  const text = String(value ?? '').trim();
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return 0;
  const [whole, fraction = ''] = text.split('.');
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
}

export function remainingRefundCents(item: Record<string, any> | null | undefined): number {
  if (!item) return 0;
  return Math.max(0, yuanToCents(item.paidAmount) - yuanToCents(item.refundedAmount));
}

export function orderAllowsRefund(order: Record<string, any> | null | undefined): boolean {
  return Boolean(order) && !CLOSED_ORDER_STATUS.has(Number(order!.orderStatus));
}
