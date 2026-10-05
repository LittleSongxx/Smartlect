#!/usr/bin/env python3
"""线程栈聚合（在被诊断的节点上运行，只读日志）。

用途：服务"CPU 空闲但响应很慢"时，平均指标看不出卡点；把最近一次线程转储里
处理请求的线程栈按"卡在哪一帧"聚合，卡点会立刻显形。

用法：python3 thread-dump-summary.py <服务日志> [线程名前缀]
"""
import re
import sys
from collections import Counter

path = sys.argv[1]
prefix = sys.argv[2] if len(sys.argv) > 2 else "exec"

code = open(path, encoding="utf-8", errors="replace").read()
start = code.rfind("Full thread dump")
if start < 0:
    print("日志里没有线程转储。请先对进程发 SIGQUIT（kill -3 <pid>）。")
    sys.exit(1)
dump = code[start:]

blocks = re.split(r"\n(?=\")", dump)
states = Counter()
frames = Counter()
samples = []
total = 0
for block in blocks:
    header = block.split("\n", 1)[0]
    if f'-{prefix}-' not in header and f'{prefix}-' not in header:
        continue
    total += 1
    m = re.search(r"java\.lang\.Thread\.State: ([A-Z_]+)", block)
    state = m.group(1) if m else "?"
    states[state] += 1
    # 取 at 栈帧的前 3 帧（跳过 java.base 包装）
    ats = [line.strip() for line in block.splitlines() if line.strip().startswith("at ")]
    app = [a for a in ats if "com.smartlect" in a] or ats
    key = " | ".join(f.replace("at ", "")[:80] for f in app[:3])
    frames[key] += 1
    if len(samples) < 3 and state != "RUNNABLE":
        samples.append((header[:70], state, app[:4]))

print(f"处理请求线程总数: {total}")
print("状态分布:", dict(states))
print("\n卡点聚合（同一栈顶的线程数）:")
for key, n in frames.most_common(6):
    print(f"  [{n:>3} 线程] {key[:200]}")
if samples:
    print("\n非 RUNNABLE 样本:")
    for header, state, stack in samples:
        print(f"  {header} — {state}")
        for line in stack:
            print(f"      {line[:120]}")
