# 压测资产（2026-09-15 三轮战役沉淀）

用法：脚本分发到压测机（node2/3 的 /root/），从被测集群内网打 node1。历史证据在
服务器 `/opt/cluster/evidence/loadtest-*/`（k6 日志、三机 CPU 曲线 CSV、窗口戳）。

| 文件 | 场景 | 关键参数 |
|---|---|---|
| `browse.js` | Java 浏览链路（首页+目录+商品页，1-3s 思考时间） | `-e VUS=N -e HOLD=100s` |
| `browse-hot.js` | 同三请求但 ~0.1s 思考时间：探 CPU 绝对墙（closed-loop） | 同上 |
| `assistant-chat.js` | AI 对话全链路（session→会话→消息→轮询 run 终态，真 LLM） | `ORIGIN` 必须是后端白名单值（见踩坑） |
| `assistant-control.js` | AI 控制面（session+推荐，无 LLM） | — |
| `loadtest-suite.sh` | browse 四档双发套件（node1 发起，证据落 /opt/cluster/evidence） | — |
| `loadtest-assistant.sh` | chat 1/2/4/8 + control 25-200 双档套件 | — |

基准数字（8c32g + JVM 三键 + Hikari 12 + 限流 400）：browse 真极限 815 req/s（CPU 墙）、
控制面 30 req/s、对话 12 轮/分钟（信号量 2 成本闸）。详见 `docs/prod-hardening/ha-cluster.md`
与 `docs/prod-hardening/ai-agent-ha.md`。

**踩坑**：① k6 打 assistant 写接口时 `Origin` 头必须是 `SMARTLECT_ALLOWED_ORIGINS` 白名单值
（默认 http://39.107.102.244），用内网地址会 100% 403 origin_denied（表现为恰好 50% 失败率）；
② 嵌套 ssh+heredoc 引号易炸，复杂逻辑写成脚本文件 scp 执行；③ `set -o pipefail` 下 `| head`
会 SIGPIPE 杀脚本，用 `sed -n 1p`；④ 全链路压测前先给旁路系统（Jaeger/日志）设内存上界。
