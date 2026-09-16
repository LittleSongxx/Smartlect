import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter, createWebHashHistory } from 'vue-router';
import { createAdminRouter, routes } from '../src/router.js';
import { resolveDesktopPath } from '../src/utils/device.js';

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

  it('every mobile route maps back to a desktop route', async () => {
    // The desktop viewport guard and MobileShell's "切换到电脑版" both resolve through
    // resolveDesktopPath, so a mobile page without an entry silently lands on /home.
    const mobile = routes.find((route) => route.name === 'MobileLayout').children.map((child) => `/m/${child.path}`.replace('/m//', '/m/'));
    const desktop = new Set(routes.find((route) => route.name === 'Layout').children.map((child) => child.path));
    const orphans = mobile.filter((path) => path !== '/m' && path !== '/m/home' && !desktop.has(resolveDesktopPath(path)));
    expect(orphans).toEqual([]);
  });
});
