# T0-4 压测报告（k6 + Locust）

日期：2026-09-14 ｜ 状态：**已完成**（四场景基线 + 单变量优化前后对比） ｜ 压测机：**服务器自身（loopback）**——数字偏保守，k6/Locust 进程与应用抢 4 核 CPU（已计入解读）；监控曲线配图：`figures/loadtest-qps.png`

## 场景与结果

### 场景①：首页/商品浏览（k6，nginx:80 全链路）

每迭代 = `GET /` + `GET /api/product/loadCategory` + `POST /api/product/loadProduct`（分页 20）+ 1-3s 思考时间。脚本 `run/cloud/loadtest/browse.js`（gitignored，服务器 `/root/loadtest/`）。

| 并发 | avg | med | p90 | p95 | 错误率 |
|---|---|---|---|---|---|
| 20 VU × 2m（优化前） | 39.5ms | 26.2ms | 93.2ms | **126.8ms** | 0%（4080 checks 全过） |
| 40 VU × 90s（优化前） | 36.0ms | 23.6ms | 84.4ms | **117.7ms** | 0% |
| 20 VU × 2m（优化后） | 17.3ms | 9.7ms | 38.1ms | **51.2ms** | 0% |
| 40 VU × 90s（优化后） | 19.1ms | 9.9ms | 42.7ms | **58.9ms** | 0% |

40 VU 折算混合请求约 45-50 req/s（含静态页）；load average 优化前 4.9 → 优化后 2.8（4 核）。

### 场景②：导购对话（k6，真实 LLM 调用，限量）

每迭代 = session → 建会话 → 发消息（触发完整 Agent 运行）→ 轮询至终态。3 VU × 2 迭代（共 6 次真实对话，控制模型计费与 SMARTLECT_MODEL_CALL_LIMIT 预算）：

- **对话 e2e（消息发出→终态）：avg 31.2s，min 26.5s / max 36.6s**——瓶颈在 LLM（DashScope qwen）与有界 ReAct 的多步工具调用，不在本机（期间 HTTP 层 p95 仅 599ms、CPU 平稳）。
- **SSE 首 token（`sse_first_token.py`，3 轮）：中位 3.05s**（2.46-3.06s），全量回放 ~19-21s。SSE 经 nginx 关缓冲配置直连网关后无回归（优化后复测 2.93s）。

### 场景③：下单-支付闭环（Locust，库存限量）

复用 growth `CommerceClient`（内部 demo 登录免短信）：选 SKU → 网关 `postOrder`（幂等键）→ `pay/mock/complete` → 轮询订单落账。3 用户、**10 单封顶**（demo 库存是 evals 共享夹具、不可回填；当前 40 SKU 共 580 件，本轮共消耗 ~13 件）：

| 操作 | med | p90 | max |
|---|---|---|---|
| postOrder（锁库存+Seata 建单+幂等） | 580ms | 1.2s | 1.18s |
| payComplete（mock 支付完成） | 190ms | 440ms | 435ms |
| orderSettled（支付落账传播） | 22ms | 45ms | 44ms |

闭环单笔总耗时 ≈ 1s，10/10 零失败、零超时。

## 优化前后对比（单变量：去掉生产链路里的 vite preview 代理）

**问题定位**：原 `/api` 路径是 `nginx:80 → vite preview(18180, Node) → gateway(18080)`——一个开发态静态服务器横在生产 API 链路里，每请求多一跳 Node 转发。

**改动**（唯一变量）：nginx 增加 `location /api/ { proxy_pass http://127.0.0.1:18080; }`（SSE 关缓冲、120s 读超时对齐），静态资源仍走 18180。`nginx -t` + reload（无中断）。

**结果**：p95 **127→51ms（-60%）**、中位 26→10ms（2.6×）、load 4.9→2.8（-43%）；SSE 首 token 无回归（3.05→2.93s）；四场景零错误保持。改动在 `run/cloud/smartlect-nginx.conf`（本地与服务器同步）。

## 容量结论（4c16g 单机，loopback 压测、数字保守）

- **浏览类**：40 并发混合流（~50 req/s）下 p95<60ms、零错误、CPU 余量充足（load 2.8/4，且含压测机自身开销）——按外推，**数百并发浏览用户无压力**，先到瓶颈的是 CPU（非中间件、非 MySQL：67 商品的数据集对 128M buffer pool 是毛毛雨，未测连接池上限）。
- **对话类**：容量受 LLM 服务限制（e2e 26-37s/次），本机在 6 并发对话期间无感知压力；增长路径是模型侧并发/预算，不是加机器。
- **交易类**：单笔闭环 ~1s、3 并发零失败；吞吐未探顶（受 demo 库存保护性限制，未做破坏性消耗）——Seata/MQ/MySQL 链路健康。

## 遇到的坑

1. **SSE「空流」三连误诊**：自研 python 基准里 `Client.request` 无条件 `resp.read()` 把流提前读干，后续读取只见 EOF——先后冤枉了 read1、时机、服务端；最终 curl -N 地面真值 + 隔离变量（终态回放正常、python 立连失败、curl 立连正常）才定位到自己客户端的 eager read。教训：流式端点的基准工具必须 lazy read。
2. **k6 二进制部署**：ECS 连不上 GitHub release 资产域——本地 `gh release download` 后 scp 过去。
3. **Locust 脚本两处小错**：漏 import `task`；3 用户首跑「0 请求」实为 grep 过滤 + spawn 前的空统计表造成的误读。
4. **压测与部署撞窗**：冒烟测试撞上 CI 部署的重启窗口（会话创建返回非 JSON）——压测前先确认 `systemctl is-active smartlect-apps`，或错开 deploy。

## 面试一句话

对单机电商+AI 全栈做了三场景基准（浏览/对话/交易闭环）并完成一次单变量优化：发现生产 API 链路里横着 vite preview 开发代理，nginx 直连网关去掉该跳数后 p95 降 60%、CPU 负载降 43%、SSE 无回归；对话链路瓶颈定位到 LLM（31s e2e、3s 首 token）而非本机，交易闭环 1 秒零失败——并用监控大盘曲线（压测窗口的 QPS 凸起）留证。
