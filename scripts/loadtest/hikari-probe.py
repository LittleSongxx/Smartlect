#!/usr/bin/env python3
"""瓶颈归因探针：在被测服务承压时采样 Hikari / Tomcat 指标（node1 执行）。

2026-09 那轮压测的教训是"605 req/s 是假墙"——真凶是 Hikari 连接池 4 条串行，
证据是「k6 的 p95 尾延迟 ≈ 连接池等连接时间（859ms≈858ms）」。这里把同样的取证
固化成脚本：边加载边采样，直接看池是不是钉满、排队有多深。

用法：python3 hikari-probe.py <服务> <端口> <采样秒数> [间隔]
"""
import json
import sys
import time
import urllib.request

WATCH = (
    "hikaricp_connections_active",
    "hikaricp_connections_idle",
    "hikaricp_connections_pending",
    "hikaricp_connections_max",
    "hikaricp_connections_acquire_seconds_max",
    "hikaricp_connections_usage_seconds_max",
    "hikaricp_connections_timeout_total",
    "tomcat_threads_busy_threads",
    "tomcat_threads_config_max_threads",
)


def scrape(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/actuator/prometheus", timeout=5) as response:
        text = response.read().decode()
    values = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        for name in WATCH:
            if line.startswith(name + "{") or line.startswith(name + " "):
                parts = line.rsplit(" ", 1)
                try:
                    values[name] = float(parts[1])
                except (IndexError, ValueError):
                    pass
    return values


def main():
    service, port, duration = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
    interval = float(sys.argv[4]) if len(sys.argv) > 4 else 5.0
    deadline = time.monotonic() + duration
    peak = {}
    samples = 0
    while time.monotonic() < deadline:
        try:
            values = scrape(port)
        except Exception as exc:  # noqa: BLE001
            print(f"  scrape failed: {exc}", flush=True)
            time.sleep(interval)
            continue
        samples += 1
        for name, value in values.items():
            peak[name] = max(peak.get(name, 0.0), value)
        print(f"  active={values.get('hikaricp_connections_active', 0):.0f} "
              f"idle={values.get('hikaricp_connections_idle', 0):.0f} "
              f"pending={values.get('hikaricp_connections_pending', 0):.0f} "
              f"acquire_max={values.get('hikaricp_connections_acquire_seconds_max', 0) * 1000:.0f}ms "
              f"tomcat_busy={values.get('tomcat_threads_busy_threads', 0):.0f}/"
              f"{values.get('tomcat_threads_config_max_threads', 0):.0f}", flush=True)
        time.sleep(interval)
    print(f"\n=== {service} 峰值（{samples} 次采样） ===")
    for name in WATCH:
        if name in peak:
            scale = 1000 if "seconds" in name else 1
            unit = "ms" if scale == 1000 else ""
            print(f"  {name} = {peak[name] * scale:.2f}{unit}")


if __name__ == "__main__":
    main()
