import { describe, expect, it } from 'vitest';
import { createMemoryHistory } from 'vue-router';
import { createAdminRouter, routes } from '../src/router.js';

describe('商家后台商品与经营入口', () => {
  it('商品列表路由存在', () => {
    expect(routes.some((route) => route.name === 'Layout' && route.children?.some((child) => child.name === 'product'))).toBe(true);
  });

  it('经营四页仍可进入', async () => {
    const router = createAdminRouter(createMemoryHistory());
    for (const name of ['merchant', 'ads', 'knowledge', 'support', 'reviewAnalysis', 'growthReport']) {
      await router.push({ name });
      expect(router.currentRoute.value.name).toBe(name);
    }
  });
});
