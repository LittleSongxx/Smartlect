import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import router from '../src/router';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('原版商城路由', () => {
  it('首页、搜索、详情、购物车与助手可解析', async () => {
    for (const path of ['/', '/search', '/search-result', '/product/622491960431656', '/assistant', '/catalog', '/browse', '/category/home', '/login']) {
      await router.push(path);
      await router.isReady();
      expect(router.currentRoute.value.path).toBe(path);
      // 没有匹配到路由的路径同样能 push 成功，所以必须单独断言 matched
      expect(router.currentRoute.value.matched.length).toBeGreaterThan(0);
    }
    expect(router.hasRoute('cart')).toBe(true);
    expect(router.resolve('/checkout').matched.length).toBeGreaterThan(0);
    expect(router.resolve('/payment/pay-1').matched.length).toBeGreaterThan(0);
    expect(router.resolve('/account/privacy').matched.length).toBeGreaterThan(0);
  });
});
