# T1-7 分布式追踪（OTel + Jaeger）

日期：2026-09-14 ｜ 状态：**已完成** ｜ 组件：OTel javaagent v2.31.1（`/opt/otel/`，25MB）+ growth 程序化插桩 + Jaeger all-in-one 1.65（monitoring compose，OTLP/HTTP :4318，UI :16686 仅 loopback/SG 兜底，内存存储）

## 做了什么

### Java 侧（约束 #7 合规）

`scripts/runtime.py` 的 Java 命令构造处注入（agent 文件存在才启用，本地无 jar 时命令与从前逐字节一致）：

```python
agent = env.get("SMARTLECT_OTEL_AGENT") or str(ROOT / "run" / "opentelemetry-javaagent.jar")
if not Path(agent).is_file():
    agent = "/opt/otel/opentelemetry-javaagent.jar"
if Path(agent).is_file():
    endpoint = env.get("SMARTLECT_OTEL_EXPORTER", "http://127.0.0.1:4318").rstrip("/")
    if endpoint.endswith("/v1/traces"):   # Java agent 只要基址（自己拼 /v1/traces、/v1/logs）
        endpoint = endpoint[: -len("/v1/traces")]
    command[1:1] = [f"-javaagent:{agent}", f"-Dotel.service.name=smartlect-{service}",
                    f"-Dotel.exporter.otlp.endpoint={endpoint}",
                    "-Dotel.exporter.otlp.protocol=http/protobuf"]
```

改后 `dev.sh check` 全绿（check_independence + runtime self-test + Java/growth/前端全量测试），服务器进程身份核验（13 进程/9 注册/8 undo 表）通过。

### growth 侧（守卫式，零侵入）

`create_app` 内 `_instrument_otel()`：`SMARTLECT_OTEL_EXPORTER` 未配置或 OTel 包未安装（本地/CI）时直接跳过；启用时 FastAPIInstrumentor（排除 /health、/metrics 噪声）+ HTTPXClientInstrumentor（出站自动注入 W3C traceparent）。依赖入 pyproject + lock（opentelemetry-sdk 1.44.0 / instrumentation 0.65b0 系，OTLP 走 HTTP 无 grpc 依赖）。

### 传播与采集

- 浏览器 → nginx → **gateway（javaagent 自动上下文）** → HTTP → **growth（FastAPI 自动提取）** → HTTP → **LLM/Java 内部调用（httpx 自动注入）**；Java→Java/MySQL 由 agent 自动埋点。
- Jaeger all-in-one 进 monitoring compose（`COLLECTOR_OTLP_ENABLED=true`），SSH 隧道看 UI。

## 怎么验证的

```text
# 全部 10 个业务服务上报
$ curl :16686/api/services
['jaeger-all-in-one','smartlect-admin','smartlect-cart','smartlect-coupon','smartlect-gateway',
 'smartlect-growth','smartlect-order','smartlect-pay','smartlect-product','smartlect-stock','smartlect-user']

# 跨服务传播：单条 trace 贯穿 gateway → growth
trace a0fe9450c7626ad3 (7 spans)
  smartlect-gateway   POST assistant                          221ms
  smartlect-growth    POST /api/assistant/conversations       183ms

# Java 内部自动埋点连 DB span 都有
trace d141f2fb1f9716ef (6 spans)
  smartlect-product   OutboxDispatchTask.dispatch              17ms
  smartlect-product   SELECT smartlect_product.local_message_outbox 1ms ...

# 「慢请求定位」故事（真实对话）：
trace 3f0992abf5855059 (8 spans, 总 3.1s)   ← figures/tracing-waterfall.png
  smartlect-gateway   POST assistant                          608ms
  smartlect-growth    POST .../messages                       564ms
  smartlect-growth    POST（出站 LLM 调用）                  2487ms  ← 瓶颈一目了然
结论：网关链路开销 ~44ms、应用处理 0.5s 级，真正的时间花在模型出站调用——
与 T0-4 压测「对话 e2e 31s、HTTP 层 p95 599ms」的结论互相印证。
```

## 遇到的坑

1. **一个 env 两个世界**：`SMARTLECT_OTEL_EXPORTER` 供 Python exporter 使用时需要含 `/v1/traces` 全路径，而 Java agent 只要基址、会自行追加 `/v1/traces`、`/v1/logs`——首版 runtime.py 直接透传导致 `4318/v1/traces/v1/traces` 404、Java 侧全部导出失败（growth 正常所以 Jaeger 里一度只有 Python 服务）。修复 = runtime.py 剥后缀（顺带又跑了一轮 dev.sh check）。
2. agent 仓库是 `open-telemetry/opentelemetry-java-instrumentation`（不是 javaagent）；ECS 拉不到 GitHub release，本地下载后 scp。
3. Jaeger host 网络下 16686/4317/4318 监听 0.0.0.0——沿用安全组只放行 22/80/443 的既有兜底，与 rabbitmq-exporter 同一处置并记录。
4. 重启窗口内压测/验证会吃到 502——`systemctl is-active` 先行。

## 面试一句话

按「agent 文件存在才启用」的条件注入把 OTel javaagent 写进统一进程管理器的命令构造（不破坏环境剥离与身份核验），growth 侧用带守卫的程序化插桩补齐 Python 端，Jaeger all-in-one 收 OTLP——上线后 10 个服务全部入图，用一条 3.1 秒的真实对话 trace 直接定位出「2.5 秒花在 LLM 出站调用、网关链路只加 44ms」，与压测结论交叉印证。
