import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { JSDOM } from 'jsdom';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import AgentChatItem from '../src/components/agent/AgentChatItem.vue';
import { session, type Run } from '../src/api/client';
import { useAgentSession } from '../src/composables/useAgentSession';

const actor = { actor_id: 'user-1', subject_type: 'user' as const, session_id: 'session-1', execution_scope_id: 'store' };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const run = (state = 'COMPLETED'): Run => ({
  agent_run_id: 'r1', conversation_id: 'c1', message_id: 'm1', state, model_mode: 'mock',
  result: { answer: '退货需按售后政策办理。' },
});

const mountItem = async (data: Run, waiting = false) => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] });
  const wrapper = mount(AgentChatItem, { props: { data, waiting }, global: { plugins: [router], stubs: { ElIcon: true } } });
  await flushPromises();
  return wrapper;
};

beforeEach(() => {
  setActivePinia(createPinia());
  // Node 25's ambient Web Storage is not the browser implementation used by this app.
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  session.value = { actor, csrf_token: 'csrf-user-1' }; localStorage.clear(); useAgentSession().reset();
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('答案反馈闭环', () => {
  it('点有用直接带 CSRF 提交反馈，成功后锁定并显示已收到反馈', async () => {
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/session')) return Promise.resolve(json(session.value));
      if (url.endsWith('/runs/r1/feedback')) return Promise.resolve(json({ agent_run_id: 'r1', rating: 'up', updated: false }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetch);
    const wrapper = await mountItem(run());
    await wrapper.get('button.feedback-btn.up').trigger('click');
    await flushPromises();
    const post = fetch.mock.calls.find(([url]) => url === '/api/assistant/runs/r1/feedback');
    expect(post).toBeTruthy();
    const options = post![1] as RequestInit;
    expect(options.method).toBe('POST');
    expect((options.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf-user-1');
    expect(JSON.parse(options.body as string)).toEqual({ rating: 'up' });
    expect(wrapper.text()).toContain('已收到反馈');
    // 已评状态仍可改评：按钮未禁用，再次点击会重新提交
    expect(wrapper.get<HTMLButtonElement>('button.feedback-btn.up').element.disabled).toBe(false);
    wrapper.unmount();
  });

  it('点没用先展开理由面板，选其他后带理由文本提交并收起', async () => {
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/session')) return Promise.resolve(json(session.value));
      if (url.endsWith('/runs/r1/feedback')) return Promise.resolve(json({ agent_run_id: 'r1', rating: 'down', updated: false }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetch);
    const wrapper = await mountItem(run());
    await wrapper.get('button.feedback-btn.down').trigger('click');
    await flushPromises();
    expect(fetch).toHaveBeenCalledTimes(0); // 理由面板未提交前不发任何请求
    expect(wrapper.find('.feedback-reasons').exists()).toBe(true);
    await wrapper.find('input[type="radio"][value="other"]').setValue();
    await wrapper.find('textarea.feedback-text').setValue('政策已经改了，回答还是旧的');
    await wrapper.get('button.feedback-submit').trigger('click');
    await flushPromises();
    const post = fetch.mock.calls.find(([url]) => url === '/api/assistant/runs/r1/feedback');
    expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual(
      { rating: 'down', reason_code: 'other', reason_text: '政策已经改了，回答还是旧的' });
    expect(wrapper.find('.feedback-reasons').exists()).toBe(false);
    expect(wrapper.text()).toContain('已收到反馈');
    wrapper.unmount();
  });

  it('提交失败显示可读错误不锁定；waiting 与 FAILED 的 run 不出现反馈条', async () => {
    const fetch = vi.fn((url: string) => {
      if (url.endsWith('/session')) return Promise.resolve(json(session.value));
      return Promise.resolve(json({ error: 'run_not_found' }, 404));
    });
    vi.stubGlobal('fetch', fetch);
    const wrapper = await mountItem(run());
    await wrapper.get('button.feedback-btn.up').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('该回答已不存在');
    expect(wrapper.text()).not.toContain('已收到反馈');
    expect(wrapper.get<HTMLButtonElement>('button.feedback-btn.up').element.disabled).toBe(false);
    wrapper.unmount();

    const waiting = await mountItem(run('RUNNING'), true);
    expect(waiting.find('.feedback-bar').exists()).toBe(false);
    waiting.unmount();

    const failed = await mountItem(run('FAILED'));
    expect(failed.find('.feedback-bar').exists()).toBe(false);
    failed.unmount();
  });
});
