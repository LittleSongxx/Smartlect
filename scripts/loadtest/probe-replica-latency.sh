#!/usr/bin/env bash
# 副本延迟对照（node1 执行）：同一次负载下，分别测三个副本的延迟增量与节点瞬时 CPU。
#
# 目的：把"平均 CPU 低但尾延迟高"这类问题定位到具体副本。2026-10-05 就是这样发现
# node2 的商品副本比另两台慢 100 倍（loadCategory 均值 4456ms vs 37ms/81ms）。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 节点拓扑的单一事实源在 deploy/cluster/nodes.env；本目录是发压/测量工具，
# 用环境变量可覆盖，默认按仓库相对路径解析。
# nodes.env 的位置随部署形态不同（仓库里在 deploy/cluster/，服务器上在 /opt/cluster/）：
# 按优先级逐个探测，避免换个地方跑就 "unbound variable"。
for candidate in "${CLUSTER_NODES_ENV:-}" "$HERE/../../deploy/cluster/nodes.env" \
                 "/opt/cluster/nodes.env" "$HERE/../nodes.env"; do
  [ -n "$candidate" ] && [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
LAUNCHER_IP="${LAUNCHER_IP:-172.17.40.108}"
SSH4="ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 root@$LAUNCHER_IP"
VUS="${1:-400}"
HOLD="${2:-60}"
BASE="${LOADTEST_BASE:-https://smartlect.cn}"

snap() { # $1=ip $2=port → "count sum max uri"
  curl -s -m 5 "http://$1:$2/actuator/prometheus" 2>/dev/null | awk -v u="$3" '
    $1 ~ /^http_server_requests_seconds_count/ && index($0, "uri=\"" u "\"") {c=$2}
    $1 ~ /^http_server_requests_seconds_sum/   && index($0, "uri=\"" u "\"") {s=$2}
    $1 ~ /^http_server_requests_seconds_max/   && index($0, "uri=\"" u "\"") {m=$2}
    END {printf "%d %f %f", c, s, m}'
}
cpu_now() { # $1=ip → 3 秒瞬时 CPU%
  ssh $CLUSTER_SSH_OPTS "root@$1" 'a=$(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat); sleep 3; b=$(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat); set -- $a $b; awk -v t1=$1 -v i1=$2 -v t2=$3 -v i2=$4 "BEGIN{printf \"%.0f\", 100*(1-(i2-i1)/(t2-t1))}"'
}

NODES="$NODE1_IP $NODE2_IP $NODE3_IP"
for uri in /product/loadCategory /product/loadProduct; do
  declare -A before
  for ip in $NODES; do before[$ip]="$(snap "$ip" 18106 "$uri")"; done
  echo "[probe] $uri 基线已取"
done
# 简化：只跟踪 loadCategory（它在大并发下最先暴露）
declare -A b
for ip in $NODES; do b[$ip]="$(snap "$ip" 18106 /product/loadCategory)"; done

$SSH4 "cd /root/loadtest && setsid nohup k6 run -e VUS=$VUS -e HOLD=${HOLD}s -e BASE=$BASE -e OUT=/tmp/probe3.json browse-k6.js > /tmp/probe3.log 2>&1 < /dev/null &" >/dev/null 2>&1
sleep 25
echo "[probe] 加载中瞬时 CPU："
for ip in $NODES; do printf "  %s: %s%%\n" "$ip" "$(cpu_now "$ip")"; done
sleep "$((HOLD - 30 > 0 ? HOLD - 30 : 10))"
echo "[probe] 负载结果："
$SSH4 "grep '^\[loadgen\]' /tmp/probe3.log | tail -1"
echo "[probe] 本次负载期间 loadCategory 的副本延迟："
for ip in $NODES; do
  read -r c1 s1 m1 <<<"${b[$ip]}"
  read -r c2 s2 m2 <<<"$(snap "$ip" 18106 /product/loadCategory)"
  dc=$((c2 - c1))
  dims=$(awk -v a="$s1" -v b="$s2" -v n="$dc" 'BEGIN{printf (n>0)?(b-a)/n*1000:0}')
  printf "  %-16s 请求 %+d  均值 %s ms  max %s ms\n" "$ip" "$dc" "$dims" "$(awk -v x="$m2" 'BEGIN{printf "%.0f", x*1000}')"
done
