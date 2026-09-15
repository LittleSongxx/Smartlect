// AI 层控制面压测（无 LLM）：visitor 会话引导 + 推荐读取，走
// nginx → gateway → growth(FastAPI) → Java introspect/召回 → MySQL 全链。
// 用法：k6 run -e BASE=http://172.21.131.151 -e VUS=100 -e HOLD=60s growth-control.js
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE || 'http://127.0.0.1';

export const options = {
  scenarios: {
    ctl: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '20s', target: Number(__ENV.VUS || 50) },
        { duration: __ENV.HOLD || '60s', target: Number(__ENV.VUS || 50) },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: { http_req_failed: ['rate<0.01'] },
};

export default function () {
  const headers = { Origin: BASE };
  const s = http.get(`${BASE}/api/assistant/session`, { headers });
  check(s, { 'session 200': (r) => r.status === 200 });
  const r = http.get(`${BASE}/api/assistant/recommendations?limit=4`, { headers });
  check(r, { 'rec 200': (resp) => resp.status === 200 });
}
