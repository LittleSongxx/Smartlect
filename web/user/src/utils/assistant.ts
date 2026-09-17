import type { Proposal, RunEvent } from '@/api/client';

export function money(cents: unknown) {
  return typeof cents === 'number' && Number.isSafeInteger(cents) && cents >= 0 ? `¥${(cents / 100).toFixed(2)}` : '金额待核实';
}
export function proposalLabel(proposal: Proposal) {
  const status = proposal.status;
  if (status === 'SUCCEEDED' && proposal.receipt?.commandStatus === 'business_completed') {
    return { order: '订单已创建，付款请单独确认', cancel: '订单已取消', refund: '退款已完成' }[proposal.action_type];
  }
  return ({ PROPOSED: '等待您的确认', CONFIRMED: '已确认，等待执行', EXECUTING: '已受理，正在核对结果',
    UNKNOWN: '结果待核实', SUCCEEDED: '操作已受理，业务终态待核实', FAILED: '操作未完成，请查看原因',
    REJECTED: '您已拒绝此操作', EXPIRED: '提案已过期，请重新生成' } as Record<string, string>)[status] || '状态待核实';
}
export function decisionVersion(proposal: Proposal) {
  return proposal.decision_version ?? proposal.version;
}
export function localDateTime(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZoneName: 'short',
  }) : '有效期待核对';
}
export function proposalExpired(proposal: Proposal, now = Date.now()) {
  return proposal.status === 'PROPOSED' && (!Number.isFinite(Date.parse(proposal.expires_at)) || Date.parse(proposal.expires_at) <= now);
}
export function readSseFrame(frame: string): RunEvent | null {
  let id = '';
  let eventName = '';
  const dataLines: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
    else if (line.startsWith('id:')) id = line.slice(3).trim();
    else if (line.startsWith('event:')) eventName = line.slice(6).trim();
  }
  const data = dataLines.join('\n');
  if (!data) return null;
  try {
    const value = JSON.parse(data);
    const fromId = Number(id);
    if (!Number.isSafeInteger(value.sequence) && Number.isSafeInteger(fromId) && fromId > 0) {
      value.sequence = fromId;
    }
    if (eventName && !value.event_type) value.event_type = eventName;
    return Number.isSafeInteger(value.sequence) && value.sequence > 0 && typeof value.agent_run_id === 'string' && typeof value.event_type === 'string' ? value : null;
  } catch { return null; }
}
export function acceptEvent(event: RunEvent, runId: string, conversationId: string, previous: number) {
  return event.agent_run_id === runId && event.conversation_id === conversationId && event.sequence > previous;
}
