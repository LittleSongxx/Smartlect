import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter, createWebHashHistory } from 'vue-router';
import adminRouter, { createAdminRouter, routes } from '../src/router.js';

// 管理端只保留桌面形态：手机端管理台下线后，路由表不再有 /m/** 与设备映射，
// 但老书签必须被重定向而不是 404（能力没删，只是不再展示）。
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

  it('路由表里不再有移动端入口，旧 /m 路径回首页而不是 404', async () => {
    const desktop = routes.find((route) => route.name === 'Layout');
    expect(desktop).toBeTruthy();
    expect(routes.some((route) => route.name === 'MobileLayout')).toBe(false);
    // 注意 /merchant、/marketing/* 也以 /m 开头，只能按段匹配
    expect(desktop.children.some((child) => child.path === '/m' || child.path.startsWith('/m/'))).toBe(false);

    // 守卫只装在默认实例上（createMemoryHistory 分支不带守卫，避免测试互相影响）
    await adminRouter.push('/m/more/ads');
    await adminRouter.isReady();
    expect(adminRouter.currentRoute.value.path).toBe('/home');
  });

  it('菜单里不再暴露已隐藏的遗留页面，但它们的路由仍然可用', async () => {
    const router = createAdminRouter(createMemoryHistory());
    for (const path of ['/product/category', '/user/address', '/data/statistics', '/data/mqCompensationLog']) {
      await router.push(path);
      expect(router.currentRoute.value.path, path).toBe(path);
    }
  });
});
