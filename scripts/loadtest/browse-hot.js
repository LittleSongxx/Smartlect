// browse 的无思考时间变体：同 3 请求/迭代，sleep 压到 ~0.1s。
// 用途：探 CPU 绝对墙（closed-loop 下吞吐=VU/迭代时长，需求速率远超 browse）。
// 与 browse 数字不可直接对比（负载模型不同），只回答"墙在哪"。
import http from 'k6/http';
import { check, sleep } from 'k6';

const VUS = Number(__ENV.VUS || 20);
const BASE = __ENV.BASE || 'http://127.0.0.1:80';

export const options = {
  scenarios: {
    hot: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: VUS },
        { duration: __ENV.HOLD || '90s', target: VUS },
        { duration: '15s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
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

  sleep(0.05 + Math.random() * 0.1);
}
