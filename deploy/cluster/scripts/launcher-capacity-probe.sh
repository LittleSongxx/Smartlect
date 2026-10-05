#!/usr/bin/env bash
# 测量发压机自身是否是瓶颈（在发压机上运行）
#
# 为什么必须测：如果发压机先饱和，测到的"服务器极限"其实是发压机的极限。
# Python asyncio 单进程处理长连接有开销，4 核机器跑上千并发时尤其要核实。
set -euo pipefail
VUS="${1:-400}"
HOLD="${2:-90}"

echo "=== 加载前基线 ==="
python3 - <<'PY'
from pathlib import Path
f = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
v = [int(x) for x in f]
print(f"  idle={v[3] + v[4]}")
PY

cd /root/loadtest
setsid nohup python3 loadgen.py browse --base https://smartlect.cn --vus "$VUS" --hold "$HOLD" \
  > /tmp/loadprobe.log 2>&1 < /dev/null &
echo "=== 加载已启动（$VUS VU / ${HOLD}s），开始采样本机 CPU ==="

python3 - "$HOLD" <<'PY'
import subprocess, sys, time
from pathlib import Path

duration = int(sys.argv[1])

def cpu_snapshot():
    f = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    v = [int(x) for x in f]
    return sum(v), v[3] + v[4]

prev_total, prev_idle = cpu_snapshot()
peak = 0.0
samples = 0
deadline = time.monotonic() + duration - 5
while time.monotonic() < deadline:
    time.sleep(3)
    total, idle = cpu_snapshot()
    busy = 100.0 * (1 - (idle - prev_idle) / (total - prev_total))
    prev_total, prev_idle = total, idle
    peak = max(peak, busy)
    samples += 1
    procs = subprocess.run(["pgrep", "-c", "-f", "loadgen.py"], capture_output=True, text=True).stdout.strip()
    print(f"  本机 CPU={busy:5.1f}%  loadgen 进程={procs}  loadavg={Path('/proc/loadavg').read_text().split()[0]}")
print(f"\n发压机 CPU 峰值 = {peak:.1f}%（{samples} 次采样）")
print("判读：接近 100% → 发压机是瓶颈，测到的不是服务器极限；明显低于 100% → 发压机不是瓶颈")
PY
sleep 4
echo "=== 发压结果 ==="
grep '^\[loadgen\]' /tmp/loadprobe.log | tail -2
