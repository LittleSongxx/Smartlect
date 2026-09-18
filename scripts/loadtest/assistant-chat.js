// AI Agent 对话链路压测：session → conversation → message → poll run 到终态。
// 每轮一次完整 Agent run（含真 LLM 调用、检索、缓存、准入闸、信号量排队）。
// 用法：k6 run -e BASE=http://172.21.131.151 -e VUS=4 -e HOLD=90s assistant-chat.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://127.0.0.1';
// Origin 必须是后端白名单里的值（与访问地址无关），否则写接口一律 403 origin_denied。
const ORIGIN = __ENV.ORIGIN || 'http://39.107.102.244';
const ROUNDS = Number(__ENV.ROUNDS || 30);
const QUERIES = ['有什么降噪耳机可以推荐？', '退货退款政策是什么？'];
const runDuration = new Trend('agent_run_duration_s');
const runOutcomes = new Counter('agent_run_outcome');

export const options = {
  scenarios: {
    chat: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: Number(__ENV.VUS || 2) },
        { duration: __ENV.HOLD || '90s', target: Number(__ENV.VUS || 2) },
        { duration: '5s', target: 0 },
      ],
    },
  },
};

function pollRun(base, rid) {
  const deadline = Date.now() + 90 * 1000;
  const start = Date.now();
  while (Date.now() < deadline) {
    const r = http.get(`${base}/api/assistant/runs/${rid}`, { headers: { Origin: ORIGIN } });
    if (r.status === 200) {
      const state = r.json('state');
      if (state !== 'CREATED' && state !== 'RUNNING') {
        runDuration.add((Date.now() - start) / 1000);
        runOutcomes.add(1, { outcome: state });
        return state;
      }
    }
    sleep(1);
  }
  runOutcomes.add(1, { outcome: 'TIMEOUT' });
  return 'TIMEOUT';
}

export default function () {
  const s = http.get(`${BASE}/api/assistant/session`, { headers: { Origin: ORIGIN } });
  if (!check(s, { 'session 200': (r) => r.status === 200 })) return;
  const headers = { Origin: ORIGIN, 'x-csrf-token': s.json('csrf_token'), 'Content-Type': 'application/json' };
  const query = QUERIES[__VU % QUERIES.length];
  for (let i = 0; i < ROUNDS; i++) {
    const c = http.post(`${BASE}/api/assistant/conversations`, '{}', { headers });
    if (!check(c, { 'conv 200': (r) => r.status === 200 })) return;
    const cid = c.json('conversation_id') || c.json('id');
    const m = http.post(`${BASE}/api/assistant/conversations/${cid}/messages`,
      JSON.stringify({ message_id: `k6-${__VU}-${__ITER}-${Date.now()}`, text: query }), { headers });
    if (m.status === 429) {
      runOutcomes.add(1, { outcome: `http429:${m.json('error') || ''}` });
      sleep(1);
      continue;
    }
    if (!check(m, { 'msg 200': (r) => r.status === 200 })) return;
    pollRun(BASE, m.json('agent_run_id'));
  }
}
