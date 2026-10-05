#!/usr/bin/env python3
"""按消费者归属 RabbitMQ 的消息投递量（node1 执行，只读）。

用途：判断"某台机器的应用更忙"是不是因为 MQ 消费倾斜。
RabbitMQ 把消息投给"能收的消费者"，若某台的消费连接更快（例如队列 leader 就在本机），
它会拿到更多消息——表现为该机 JVM 的 CPU 明显更高，而线程数与配置都相同。

用法：python3 rabbit-consumer-attribution.py
"""
import base64
import json
import sys
import urllib.request
from collections import defaultdict

RT = "/opt/smartlect/run/runtime.env"
env = dict(line.split("=", 1) for line in open(RT).read().splitlines()
           if line and not line.startswith("#") and "=" in line)
auth = base64.b64encode(f"{env['SMARTLECT_RABBIT_USER']}:{env['SMARTLECT_RABBIT_PASSWORD']}".encode()).decode()


def api(path):
    req = urllib.request.Request(f"http://127.0.0.1:15672/api{path}")
    req.add_header("Authorization", "Basic " + auth)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


total = api("/overview")["message_stats"]
print("=== 全集群消息速率 ===")
for key in ("publish", "deliver_get", "ack", "confirm", "redeliver"):
    d = total.get(f"{key}_details") or {}
    if d:
        print(f"  {key:12} {d.get('rate', 0):8.2f} /s")

print()
print("=== 各连接的消费速率（按客户端所在主机聚合）===")
by_peer = defaultdict(lambda: {"deliver": 0.0, "ack": 0.0, "conns": 0, "channels": 0})
for conn in api("/connections"):
    peer = (conn.get("peer_host") or "?").split(":")[0]
    stats = conn.get("recv_cnt", 0)
    by_peer[peer]["conns"] += 1
    by_peer[peer]["channels"] += conn.get("channels", 0)
for ch in api("/channels"):
    peer = (ch.get("peer_host") or "?").split(":")[0]
    d = ch.get("message_stats") or {}
    by_peer[peer]["deliver"] += ((d.get("deliver_get_details") or {}).get("rate") or 0)
    by_peer[peer]["ack"] += ((d.get("ack_details") or {}).get("rate") or 0)

for peer, v in sorted(by_peer.items(), key=lambda kv: -kv[1]["deliver"]):
    print(f"  {peer:16} 连接 {v['conns']:>3}  信道 {v['channels']:>4}  "
          f"投递 {v['deliver']:8.2f}/s  ack {v['ack']:8.2f}/s")

print()
print("=== 队列 leader 分布（quorum 的 leader 承担落盘）===")
leaders = defaultdict(int)
for q in api("/queues/%2Fsmartlect"):
    leaders[q.get("leader") or "none"] += 1
for name, n in sorted(leaders.items(), key=lambda kv: -kv[1]):
    print(f"  {name:28} {n} 个队列")
