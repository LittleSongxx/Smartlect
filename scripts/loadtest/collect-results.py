#!/usr/bin/env python3
"""汇总压测证据目录里的 loadgen JSON 为一张表（node1 执行，只读）。

用法：python3 collect-results.py /opt/cluster/evidence/loadtest-YYYYmmdd-HHMM
"""
import glob
import json
import os
import sys


def main():
    ev = sys.argv[1]
    rows = []
    for path in sorted(glob.glob(os.path.join(ev, "loadgen-*.json"))):
        with open(path) as handle:
            rows.append(json.load(handle))
    rows.sort(key=lambda d: (d["kind"], d["vus"]))
    header = f"{'场景':<8}{'总并发':>7}{'req/s':>9}{'p50(ms)':>10}{'p95(ms)':>11}{'p99(ms)':>11}{'错误率':>9}   状态码"
    print(header)
    print("-" * len(header))
    for d in rows:
        lat = d["latency_ms"]
        codes = " ".join(f"{k}:{v}" for k, v in sorted(d["status"].items()))
        print(f"{d['kind']:<8}{d['vus']:>7}{d['qps']:>9}{lat['p50']:>10}{lat['p95']:>11}"
              f"{lat['p99']:>11}{d['error_rate'] * 100:>8.2f}%   {codes}")
    if rows:
        print()
        print("按请求类型细分（p50/p95）：")
        for d in rows:
            parts = [f"{name}={v['count']}次 p50={v['p50']} p95={v['p95']}"
                     for name, v in sorted(d["by_request"].items())]
            print(f"  {d['kind']}@{d['vus']}VU: " + " | ".join(parts))


if __name__ == "__main__":
    main()
