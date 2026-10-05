#!/usr/bin/env python3
"""从阶梯压测结果算拐点与极限（在读证据的机器上运行，只读）。

口径定义（写死在代码里，便于复算与被质疑时核对）：
  低负载基线 p95  = 阶梯中最小并发档的 p95
  拐点（延迟口径）= 使 p95 ≥ KNEE_FACTOR × 基线 p95 的最小并发
  拐点（吞吐口径）= 吞吐相对上一档增幅 < MARGIN 的那个并发（吞吐不再随并发增长）
  峰值吞吐        = 各档 qps 的最大值
  可持续极限      = 峰值及其相邻档中，p95 仍低于 P95_CEILING_MS 的最大 qps
用法：python3 analyze-knee.py <证据目录> [<证据目录> ...]
"""
import glob
import json
import os
import sys

KNEE_FACTOR = 2.0
MARGIN = 0.10
P95_CEILING_MS = 1000.0


def analyze(label, rows):
    rows.sort(key=lambda d: d["vus"])
    if not rows:
        return
    baseline = rows[0]["latency_ms"]["p95"]
    threshold = KNEE_FACTOR * baseline

    knee_latency = next((d for d in rows if d["latency_ms"]["p95"] >= threshold), None)

    knee_throughput = None
    for prev, cur in zip(rows, rows[1:]):
        if prev["qps"] > 0 and (cur["qps"] - prev["qps"]) / prev["qps"] < MARGIN:
            knee_throughput = cur
            break

    peak = max(rows, key=lambda d: d["qps"])
    sustainable = [d for d in rows if d["latency_ms"]["p95"] < P95_CEILING_MS]
    best_sustainable = max(sustainable, key=lambda d: d["qps"]) if sustainable else None

    print(f"\n===== {label} =====")
    print(f"低负载基线 p95 = {baseline}ms（{rows[0]['vus']} 并发档）")
    if knee_latency:
        lat = knee_latency["latency_ms"]
        print(f"拐点(延迟口径, p95≥{threshold:.0f}ms) = {knee_latency['vus']} 并发 "
              f"→ {knee_latency['qps']} req/s, p95={lat['p95']}ms, p99={lat['p99']}ms")
    else:
        print(f"拐点(延迟口径)：测到 {rows[-1]['vus']} 并发仍未越过 {threshold:.0f}ms —— 拐点更高，需加大并发")
    if knee_throughput:
        print(f"拐点(吞吐口径, 增幅<{MARGIN:.0%}) = {knee_throughput['vus']} 并发 → {knee_throughput['qps']} req/s")
    print(f"峰值吞吐 = {peak['qps']} req/s @ {peak['vus']} 并发 "
          f"(p50={peak['latency_ms']['p50']}ms p95={peak['latency_ms']['p95']}ms "
          f"p99={peak['latency_ms']['p99']}ms 错误率={peak['error_rate'] * 100:.2f}%)")
    if best_sustainable:
        print(f"可持续极限(p95<{P95_CEILING_MS:.0f}ms) = {best_sustainable['qps']} req/s @ "
              f"{best_sustainable['vus']} 并发 (p95={best_sustainable['latency_ms']['p95']}ms)")
    print(f"{'并发':>7}{'req/s':>10}{'p50':>10}{'p95':>11}{'p99':>11}{'错误率':>9}")
    for d in rows:
        lat = d["latency_ms"]
        print(f"{d['vus']:>7}{d['qps']:>10}{lat['p50']:>10}{lat['p95']:>11}{lat['p99']:>11}"
              f"{d['error_rate'] * 100:>8.2f}%")


def main():
    groups = {}
    for directory in sys.argv[1:]:
        for path in glob.glob(os.path.join(directory, "loadgen-*.json")):
            with open(path) as handle:
                data = json.load(handle)
            label = f"{data['label'] or '?'} / {data['kind']}"
            groups.setdefault(label, []).append(data)
    for label in sorted(groups):
        analyze(label, groups[label])


if __name__ == "__main__":
    main()
