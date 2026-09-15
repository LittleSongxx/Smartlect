// 场景①：首页/商品浏览（无状态读链路：nginx:80 → vite preview → gateway → Java）
// 用法：k6 run -e VUS=20 browse.js   （BASE 可覆盖）
import http from 'k6/http';
import { check, sleep } from 'k6';

const VUS = Number(__ENV.VUS || 20);
const BASE = __ENV.BASE || 'http://127.0.0.1:80';

export const options = {
  scenarios: {
    browse: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: VUS },
        { duration: __ENV.HOLD || '2m', target: VUS },
        { duration: '15s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800'],
  },
};

export default function () {
  const home = http.get(`${BASE}/`);
  check(home, { 'home 200': (r) => r.status === 200 });

  const cat = http.get(`${BASE}/api/product/loadCategory`);
  check(cat, { 'category 200': (r) => r.status === 200 });

  const page = http.post(`${BASE}/api/product/loadProduct`, 'page=1&pageSize=20', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  check(page, { 'products 200': (r) => r.status === 200 });

  sleep(1 + Math.random() * 2);
}
