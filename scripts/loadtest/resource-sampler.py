#!/usr/bin/env python3
"""轻量资源采样器（各节点各自运行，只读 /proc）。

不启动 Prometheus/Grafana 是刻意的：在被测机上跑监控栈本身会抢 CPU/内存，
把测量结果污染掉（2026-09 那轮就是 Jaeger 吃满内存把宿主打进假死）。
这里只读 /proc，采样成本可忽略。

用法：python3 resource-sampler.py <输出文件> <时长秒> [间隔秒]
输出：TSV，列为 时间戳/CPU使用率%/内存使用率%/load1
"""
import sys
import time
from pathlib import Path


def read_cpu():
    fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = [int(v) for v in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def read_mem():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0])
    total = info["MemTotal"]
    available = info.get("MemAvailable", info.get("MemFree", 0))
    return (total - available) / total * 100.0


def main():
    out = Path(sys.argv[1])
    duration = float(sys.argv[2])
    interval = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    deadline = time.monotonic() + duration
    with out.open("w") as handle:
        handle.write("ts\tcpu_pct\tmem_pct\tload1\n")
        prev_total, prev_idle = read_cpu()
        while time.monotonic() < deadline:
            time.sleep(interval)
            total, idle = read_cpu()
            delta_total = total - prev_total
            delta_idle = idle - prev_idle
            cpu = 100.0 * (1 - delta_idle / delta_total) if delta_total else 0.0
            prev_total, prev_idle = total, idle
            load1 = Path("/proc/loadavg").read_text().split()[0]
            handle.write(f"{int(time.time())}\t{cpu:.1f}\t{read_mem():.1f}\t{load1}\n")
            handle.flush()


if __name__ == "__main__":
    main()
