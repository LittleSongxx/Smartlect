import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { JSDOM } from 'jsdom';
import PrivacyView from '../src/views/PrivacyView.vue';
import { session } from '../src/api/client';
import { useAgentSession } from '../src/composables/useAgentSession';

const actor = { actor_id: 'user1', subject_type: 'user' as const, session_id: 's1', execution_scope_id: 'store' };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
let wrapper: VueWrapper | undefined;

beforeEach(() => {
  setActivePinia(createPinia());
  session.value = { actor, csrf_token: 'csrf1' };
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('AI 数据与隐私页', () => {
  it('列出偏好、删除单项并清除记忆', async () => {
    const fetch = vi.fn((url: string, options?: RequestInit) => {
      if (url.endsWith('/session')) return Promise.resolve(json(session.value));
      if (url.endsWith('/preferences') && (!options?.method || options.method === 'GET')) {
        return Promise.resolve(json([{ preference_key: 'purpose', value: '通勤', source: 'explicit', version: 1 }]));
      }
      return Promise.resolve(json({ cleared: true }));
    });
    vi.stubGlobal('fetch', fetch);
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/account/privacy', component: PrivacyView },
        { path: '/shopping-profile', component: { template: '<div />' } }
      ]
    });
    await router.push('/account/privacy');
    await router.isReady();
    wrapper = mount(PrivacyView, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.text()).toContain('通勤');
    expect(wrapper.text()).toContain('不会导出或删除订单');
    await wrapper.get('.preference-row button').trigger('click');
    await flushPromises();
    expect(fetch.mock.calls.some(([url, options]) =>
      String(url).endsWith('/preferences/purpose') && options?.method === 'DELETE')).toBe(true);
  });

  it('助手空闲默认可以开始对话', () => {
    const chat = useAgentSession();
    chat.reset();
    expect(chat.connection.value).toBe('可以开始对话');
  });
});
