# 三节点应用集群压测证据（2026-10-05）

对应记录：[docs/改动记录/2026-10-05/三节点应用集群与性能压测.md](../../../docs/改动记录/2026-10-05/三节点应用集群与性能压测.md)

## 目录说明

| 目录 | 内容 | 是否作为结论依据 |
|---|---|---|
| `single-k6/` | **形态 A（单机）精测**：k6，200→1600 并发共 7 档，解除限流 | ✅ 结论依据 |
| `cluster-k6-warm/` | **形态 B（三节点集群）精测**：k6，200→2000 并发共 8 档，解除限流，JVM 已预热 | ✅ 结论依据 |
| `cluster-k6-cold-discarded/` | 集群首轮阶梯（400→2400）。**已作废**：形态切换后立刻开跑，node2/node3 的 JVM 尚在预热，起始档 p95 2.5s 与相邻档（300 并发 43.7ms）严重背离 | ❌ 仅作方法论留证 |
| `early-rig-limited/` | 早期用自研 Python 发压器的全部档位（含交易闭环 order 档） | ⚠️ 见下 |
| `knee-analysis.txt` | 拐点与峰值的分析输出（由 `deploy/cluster/scripts/analyze-knee.py` 生成，口径写死在脚本里） | ✅ 结论依据 |

## 为什么有两批发压数据

自研的 Python(asyncio) 发压器在 **400 并发 TLS 长连接下把 4 核发压机 CPU 打满 100%**——
用它测出的"277 req/s 墙"是发压机的极限而非被测系统的。改用 k6（Go）后同一台机器可推到
2000+ req/s，才探到真实天花板。故：

- **浏览链路的极限值只采信 k6 那两批**（`single-k6/`、`cluster-k6-warm/`）
- `early-rig-limited/` 里的**交易闭环（order）档位仍有效**：该场景并发只有 3/5/10，
  远未触及发压机瓶颈；但这批数据是 Python 发压器跑的，`by_request` 里保留了
  加购/下单/支付的分项延迟

## 单档 JSON 的字段

与 `scripts/loadtest/loadgen.py`、`deploy/cluster/scripts/browse-k6.js` 两份发压器**同构**，
`analyze-knee.py` 通吃：

```json
{
  "kind": "browse", "vus": 600, "hold": "60s", "launcher": "k6",
  "requests": 50631, "qps": 803.66, "error_rate": 0.0,
  "latency_ms": {"avg":..., "p50":5.89, "p90":..., "p95":234.88, "p99":1040.29, "max":...},
  "status": {"200": 50631}
}
```

## 拐点口径（可复算）

`analyze-knee.py` 里写死的三条定义：

- 低负载基线 p95 = 阶梯中**最小并发档**的 p95
- 延迟拐点 = p95 首次 ≥ **2× 基线** 的最小并发
- 吞吐拐点 = 吞吐相对上一档增幅 < **10%** 的并发
- 可持续极限 = 峰值及其相邻档中 p95 < **1000ms** 的最大吞吐

## 复现方式

```bash
# 发压（形态切换 + 阶梯 + 证据采集，全部在 node1 驱动发压机）
LOAD_ENGINE=k6 BROWSE_TIERS="200 400 600 800 1200 1600" HOLD=60 \
  bash deploy/cluster/scripts/loadtest-suite.sh cluster
# 分析
python3 deploy/cluster/scripts/analyze-knee.py eval/verification/cluster-loadtest-20261005/single-k6
```
