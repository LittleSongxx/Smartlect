import { onUnmounted, ref, toValue, watch, type MaybeRefOrGetter } from 'vue';
import { aiPost, ApiError, errorText, ownerKey, session } from '@/api/client';
import type { Promotion } from '@/api/traffic';

export function promotionProductPath(item: Promotion) {
  const sku = item.propertyValueIds ? `?sku=${encodeURIComponent(String(item.propertyValueIds))}` : '';
  return `/product/${item.productId}${sku}`;
}

export function usePromotionCharge(item: MaybeRefOrGetter<Promotion | null | undefined>) {
  const clicking = ref(false);
  const error = ref('');
  const unavailable = ref(false);
  let observer: IntersectionObserver | undefined;
  let visible = false;
  let alive = true;
  let exposed = false;
  let clicked = false;
  let exposing: Promise<boolean> | undefined;
  let exposureId = crypto.randomUUID();
  let clickId = crypto.randomUUID();
  const owner = session.value ? ownerKey(session.value.actor) : '';

  const currentItem = () => toValue(item) || null;
  const sameOwner = () => alive && !!session.value && owner === ownerKey(session.value.actor);

  function resetReceipts() {
    exposed = false;
    clicked = false;
    exposing = undefined;
    exposureId = crypto.randomUUID();
    clickId = crypto.randomUUID();
    unavailable.value = false;
    error.value = '';
  }

  function rejected(reason: unknown) {
    if (!sameOwner()) return;
    unavailable.value = reason instanceof ApiError && [400, 403, 404, 409, 410, 422].includes(reason.status);
    error.value = unavailable.value
      ? '这条推广的可投状态已变化，请刷新后查看。'
      : `推广暂时无法打开，请稍后重试。${errorText(reason)}`;
  }

  async function expose(): Promise<boolean> {
    const promo = currentItem();
    if (!sameOwner() || !promo || unavailable.value) return false;
    if (exposed) return true;
    if (exposing) return exposing;
    if (!visible || document.visibilityState !== 'visible') return false;
    exposing = (async () => {
      try {
        const receipt = await aiPost('/ads/exposures', {
          exposure_id: exposureId,
          creative_id: promo.creative_id,
          expected_campaign_version: promo.campaign_version,
          expected_creative_version: promo.creative_version
        }, AbortSignal.timeout(5000));
        if (!sameOwner()) return false;
        if (receipt.exposure_id !== exposureId || receipt.creative_id !== promo.creative_id
          || receipt.campaign_version !== promo.campaign_version
          || receipt.creative_version !== promo.creative_version) {
          throw new ApiError(409, 'ad_exposure_version_changed');
        }
        exposed = true;
        error.value = '';
        return true;
      } catch (reason) {
        rejected(reason);
        return false;
      } finally {
        exposing = undefined;
      }
    })();
    return exposing;
  }

  function recordVisible() {
    if (sameOwner() && visible && !error.value) void expose();
  }

  async function activate(): Promise<boolean> {
    const promo = currentItem();
    if (!sameOwner() || !promo || clicking.value || unavailable.value) return false;
    clicking.value = true;
    try {
      visible = true;
      if (!await expose() || !sameOwner()) return false;
      if (!clicked) {
        const receipt = await aiPost('/ads/clicks', {
          click_id: clickId,
          exposure_id: exposureId
        }, AbortSignal.timeout(5000));
        if (!sameOwner()) return false;
        if (receipt.status !== 'CHARGED' || receipt.click_id !== clickId || receipt.exposure_id !== exposureId) {
          throw new Error('未收到有效推广点击回执。');
        }
        clicked = true;
      }
      error.value = '';
      return true;
    } catch (reason) {
      rejected(reason);
      return false;
    } finally {
      clicking.value = false;
    }
  }

  function observe(el: Element | null) {
    observer?.disconnect();
    if (!el || typeof IntersectionObserver === 'undefined') return;
    observer = new IntersectionObserver((entries) => {
      visible = entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.5);
      recordVisible();
    }, { threshold: 0.5 });
    observer.observe(el);
  }

  function disconnect() {
    alive = false;
    observer?.disconnect();
    document.removeEventListener('visibilitychange', recordVisible);
  }

  document.addEventListener('visibilitychange', recordVisible);
  onUnmounted(disconnect);
  watch(() => {
    const promo = currentItem();
    return promo ? `${promo.creative_id}:${promo.campaign_version}:${promo.creative_version}` : '';
  }, (next, prev) => {
    if (prev && next !== prev) resetReceipts();
    recordVisible();
  });

  return { expose, activate, observe, disconnect, clicking, error, unavailable };
}
