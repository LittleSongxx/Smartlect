import { aiPost } from './client';

export interface RecommendationTouch { recommendation_id: string; position: number }
export interface VisitorBinding { bound: boolean; conversation_ids: string[]; assignment_conflict: boolean }
export interface RecommendationList {
  recommendation_id: string; items: Record<string, any>[]; assignment_id: string; strategy_version: string; ranking_mode: string;
}
export interface Promotion {
  creative_id: string; campaign_id: string; productId: string; sku_key: string; propertyValueIds: string;
  productName: string; copy_text: string; price_cents: number; stock: number; specification: string;
  creative_version: number; campaign_version: number; reasons?: string[]; cover?: string;
}
const entryId = crypto.randomUUID();
let landing: Promise<boolean> | undefined;

// A page reload is a new entry; component remounts, focus and account changes are not.
export function recordLanding() {
  return landing ??= aiPost('/traffic/landing', { entry_id: entryId }, AbortSignal.timeout(2000)).then(() => true, () => false);
}
export async function bindVisitor(): Promise<VisitorBinding | null> {
  try { return await aiPost<VisitorBinding>('/traffic/bind', {}, AbortSignal.timeout(2000)); }
  catch { return null; }
}
export function recommendationTouch(item: Record<string, any>): RecommendationTouch | null {
  return typeof item.recommendation_id === 'string' && item.recommendation_id.length > 0 && item.recommendation_id.length <= 128 &&
    Number.isSafeInteger(item.position) && item.position > 0 && item.position <= 8 ? { recommendation_id: item.recommendation_id, position: item.position } : null;
}
export async function reportExposure(recommendationId: string, positions: number[]) {
  try { await aiPost(`/recommendations/${encodeURIComponent(recommendationId)}/exposures`, { positions }, AbortSignal.timeout(2000)); return true; }
  catch { return false; }
}
export async function reportClick(touch: RecommendationTouch) {
  try { await aiPost(`/recommendations/${encodeURIComponent(touch.recommendation_id)}/clicks`, { position: touch.position }, AbortSignal.timeout(2000)); return true; }
  catch { return false; }
}
