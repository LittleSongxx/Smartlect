import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import router from '../src/router';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('原版商城路由', () => {
  it('首页、搜索、详情、购物车与助手可解析', async () => {
    for (const path of ['/', '/search-portal', '/search-result', '/product/622491960431656', '/assistant', '/catalog', '/browse', '/login']) {
      await router.push(path);
      await router.isReady();
      expect(router.currentRoute.value.path).toBe(path);
    }
    expect(router.hasRoute('cart')).toBe(true);
    expect(router.resolve('/checkout').matched.length).toBeGreaterThan(0);
    expect(router.resolve('/payment/pay-1').matched.length).toBeGreaterThan(0);
    expect(router.resolve('/account/privacy').matched.length).toBeGreaterThan(0);
  });
});
