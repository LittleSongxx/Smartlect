import { afterEach, expect, it, vi } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { aiPost, javaPost, loadSession, session, type Session } from '../src/api/client';

afterEach(() => { session.value = null; vi.unstubAllGlobals(); });

it('合并首次会话、隔离超时，写前重新核验且旧响应不能覆盖登录身份', async () => {
  const visitor: Session = { actor: { actor_id: 'visitor1', subject_type: 'visitor', session_id: 's1', execution_scope_id: 'store' }, csrf_token: 'visitor-csrf' };
  const user: Session = { actor: { ...visitor.actor, actor_id: 'user1', subject_type: 'user', session_id: 's2' }, csrf_token: 'user-csrf' };
  const pending: Array<(value: unknown, status?: number) => void> = [];
  const fetch = vi.fn((_url: string, _options?: RequestInit) => new Promise<Response>((resolve) => {
    pending.push((value, status = 200) => resolve(new Response(JSON.stringify(value), { status })));
  }));
  vi.stubGlobal('fetch', fetch); session.value = null;
  const timeout = new AbortController();
  const exposure = aiPost('/recommendations/rec1/exposures', { positions: [1] }, timeout.signal);
  const expired = expect(exposure).rejects.toMatchObject({ name: 'AbortError' });
  const startup = loadSession(); const focus = loadSession();
  expect(fetch).toHaveBeenCalledTimes(1);
  timeout.abort(); await expired;
  expect(fetch.mock.calls[0]![1]?.signal?.aborted).not.toBe(true);
  pending[0]!(visitor);
  expect(await startup).toEqual(visitor); expect(await focus).toEqual(visitor);
  expect(fetch).toHaveBeenCalledTimes(1);

  const landing = aiPost('/traffic/landing', { entry_id: 'entry1' });
  expect(fetch.mock.calls[1]![0]).toBe('/api/assistant/session');
  pending[1]!({ ...visitor, csrf_token: 'fresh-csrf' }); await flushPromises();
  expect(fetch.mock.calls[2]).toEqual(['/api/assistant/traffic/landing', expect.objectContaining({
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'fresh-csrf' },
  })]);
  pending[2]!({ recorded: true }); await landing;

  const oldRead = loadSession();
  const login = javaPost('/account/login', { email: 'synthetic@example.invalid' });
  pending[4]!({ code: 200, data: {} }); await login;
  const loggedIn = loadSession();
  expect(fetch.mock.calls[5]![0]).toBe('/api/assistant/session');
  pending[5]!(user); await loggedIn;
  pending[3]!(visitor); expect(await oldRead).toEqual(user);
  expect(session.value).toEqual(user); expect(fetch).toHaveBeenCalledTimes(6);

  const staleWrite = aiPost('/preferences/purpose', { value: 'prior account preference' });
  const rejected = expect(staleWrite).rejects.toThrow('账号已切换');
  pending[6]!(visitor); await rejected;
  expect(fetch).toHaveBeenCalledTimes(7);
});
