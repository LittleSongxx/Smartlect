import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter, createWebHashHistory } from 'vue-router';
import { createAdminRouter, routes } from '../src/router.js';

describe('管理端 hash 路由', () => {
  it('刷新等价的路由表停在 ads 与 support', async () => {
    const router = createAdminRouter(createMemoryHistory());
    await router.push('/ads');
    await router.isReady();
    expect(router.currentRoute.value.name).toBe('ads');
    await router.push('/support');
    expect(router.currentRoute.value.name).toBe('support');
    await router.push('/order/refundReview');
    expect(router.currentRoute.value.name).toBe('退款复核');
  });

  it('hash history 解析 #/ads 与 #/support', async () => {
    const router = createRouter({ history: createWebHashHistory(), routes });
    await router.push('/ads');
    await router.isReady();
    expect(router.currentRoute.value.name).toBe('ads');
    await router.push('/support');
    expect(router.currentRoute.value.name).toBe('support');
  });
});
