// 浏览链路压测（k6）—— 输出格式与 scripts/loadtest/loadgen.py 对齐，
// 这样同一套 analyze-knee.py 可以同时分析两种发压器的结果。
//
// 用法：
//   k6 run -e VUS=400 -e HOLD=90s -e BASE=https://smartlect.cn -e OUT=/tmp/s.json browse-k6.js
//
// 两个坑必须记住（都踩过）：
//   1) 业务错误是 HTTP 200 包着 {"status":"error"} 返回的，只看状态码会把失败全算成成功。
//      2026-10-05 就因为漏了这一层，把 10 万次参数校验失败当成"零错误"报了出去。
//   2) /product/loadProduct 的参数是 pageNo（@NotNull），不是 page；发错了每个请求都会
//      在校验层被打回，测出来的吞吐是"快速失败"的吞吐，不是真实处理的吞吐。
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const VUS = Number(__ENV.VUS || 100);
const BASE = (__ENV.BASE || 'https://smartlect.cn').replace(/\/$/, '');
const HOLD = __ENV.HOLD || '90s';

// 不用标签化计数器：handleSummary 里按标签投影出来的键名随版本变化，
// 显式分档最稳，也正好覆盖我们要看的几种结局。
const cOk = new Counter('status_ok');
const c429 = new Counter('status_429');
const c4xx = new Counter('status_other_4xx');
const c5xx = new Counter('status_5xx');
const cBizErr = new Counter('business_errors');
const bizErrRate = new Rate('business_error_rate');

export const options = {
  scenarios: {
    browse: {
      executor: 'constant-vus',
      vus: VUS,
      duration: HOLD,
      gracefulStop: '3s',
    },
  },
  insecureSkipTLSVerify: true,
  // 默认汇总只给 avg/min/med/max/p(90)/p(95)：p50 与 p99 必须显式声明才有值
  summaryTrendStats: ['avg', 'min', 'med', 'p(50)', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

/** 接口用 ResponseVO 包一层：HTTP 200 也可能是业务失败，必须解 body 才能看见。 */
function isBusinessError(response) {
  if (!response.body || response.body.length > 65536) {
    return false;
  }
  const head = response.body.trimStart();
  if (!head.startsWith('{')) {
    return false; // 静态资源/HTML 不算
  }
  try {
    const parsed = JSON.parse(response.body);
    return parsed && typeof parsed === 'object' && parsed.status === 'error';
  } catch (e) {
    return false;
  }
}

function track(response) {
  if (response.status >= 500) c5xx.add(1);
  else if (response.status === 429) c429.add(1);
  else if (response.status >= 400) c4xx.add(1);
  else cOk.add(1);
  const bad = isBusinessError(response);
  if (bad) cBizErr.add(1);
  bizErrRate.add(bad ? 1 : 0);
  return response;
}

export default function () {
  track(http.get(`${BASE}/`));
  track(http.get(`${BASE}/api/product/loadCategory`));
  // 参数名是 pageNo（@NotNull）；pageSize 这个接口根本不接。
  track(http.post(`${BASE}/api/product/loadProduct`, 'pageNo=1', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  }));
  sleep(1 + Math.random() * 2);
}

export function handleSummary(data) {
  const m = data.metrics;
  const reqs = m.http_reqs ? m.http_reqs.values.count : 0;
  const rate = m.http_reqs ? m.http_reqs.values.rate : 0;
  const d = m.http_req_duration ? m.http_req_duration.values : {};
  const count = (name) => (m[name] ? m[name].values.count : 0);
  const status = {};
  if (count('status_ok')) status['200'] = count('status_ok');
  if (count('status_429')) status['429'] = count('status_429');
  if (count('status_other_4xx')) status['4xx'] = count('status_other_4xx');
  if (count('status_5xx')) status['5xx'] = count('status_5xx');
  const ok = count('status_ok');
  const bizErrors = count('business_errors');
  const summary = {
    kind: 'browse',
    label: __ENV.LABEL || '',
    launcher: 'k6',
    base: BASE,
    vus: VUS,
    hold: HOLD,
    requests: reqs,
    duration_s: rate > 0 ? reqs / rate : 0,
    qps: rate,
    ok,
    error_rate: reqs > 0 ? (reqs - ok) / reqs : 0,
    business_errors: bizErrors,
    business_error_rate: reqs > 0 ? bizErrors / reqs : 0,
    latency_ms: {
      avg: d.avg || 0,
      p50: d['p(50)'] || 0,
      p90: d['p(90)'] || 0,
      p95: d['p(95)'] || 0,
      p99: d['p(99)'] || 0,
      max: d.max || 0,
    },
    status,
    by_request: {},
  };
  const out = {};
  out[__ENV.OUT || '/tmp/k6-summary.json'] = JSON.stringify(summary, null, 2);
  out.stdout = `\n[loadgen] browse vus=${VUS} -> ${rate.toFixed(2)} req/s | ` +
    `p50=${summary.latency_ms.p50.toFixed(1)}ms p95=${summary.latency_ms.p95.toFixed(1)}ms ` +
    `p99=${summary.latency_ms.p99.toFixed(1)}ms | 传输层错误=${(summary.error_rate * 100).toFixed(2)}% ` +
    `| 业务错误=${bizErrors}(${(summary.business_error_rate * 100).toFixed(2)}%) ` +
    `| status=${JSON.stringify(status)}\n`;
  return out;
}
