#!/usr/bin/env bash
# 压测编排（node1 执行，驱动发压机 node4）
#
# 形态切换只动两处：node2/node3 的应用副本起停 + nginx 的网关 upstream。
# node1 自身的 runtime.env 全程不变——这样 A/B 两形态的差异最小、切换在一分钟内完成。
#
# 用法：
#   bash loadtest-suite.sh single            # 形态 A：应用只在 node1（基线）
#   bash loadtest-suite.sh cluster           # 形态 B：三节点应用集群
#   bash loadtest-suite.sh form cluster      # 只切形态不压测
#
# 证据落 /opt/cluster/evidence/loadtest-<窗口>/
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
LAUNCHER="${LAUNCHER_IP:-172.17.40.108}"
KEY=/root/.ssh/id_ed25519
SSH4="ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@$LAUNCHER"
EV="/opt/cluster/evidence/loadtest-$(date +%Y%m%d-%H%M)"
BASE="${LOADTEST_BASE:-https://smartlect.cn}"
ADMIN="http://$NODE1_IP:18101"
PRODUCT="http://$NODE1_IP:18106"
STOCK="http://$NODE1_IP:18108"
PAY="http://$NODE1_IP:18103"
BROWSE_TIERS="${BROWSE_TIERS:-100 200 400 600 800 1200}"
ORDER_TIERS="${ORDER_TIERS:-3 5 10}"
HOLD="${HOLD:-100}"

log() { echo "[suite $(date +%T)] $*"; }
remote_apps() { ssh $CLUSTER_SSH_OPTS "root@$1" "systemctl $2 smartlect-apps" >/dev/null; }

set_form() {
  case "$1" in
    cluster)
      log "形态=集群：先起 node2/node3 副本，再挂三网关 upstream"
      remote_apps "$NODE2_IP" start
      remote_apps "$NODE3_IP" start
      bash "$HERE/nginx-cluster.sh" apply | tail -1
      ;;
    single)
      log "形态=单机：先撤 upstream（避免打到即将停掉的网关），再停 node2/node3 副本"
      bash "$HERE/nginx-cluster.sh" revert | tail -1
      remote_apps "$NODE2_IP" stop
      remote_apps "$NODE3_IP" stop
      ;;
    *) echo "unknown form: $1"; exit 2;;
  esac
  sleep 5
  log "形态就绪：$(bash "$HERE/nginx-cluster.sh" status 2>/dev/null | grep -c 'proxy_pass http://smartlect_gateway' || true) 处引用 upstream"
}

run_load() { # $1=kind $2=vus
  local kind="$1"
  local vus="$2"
  local out="$EV/loadgen-$FORM-$kind-$vus.json"
  log "  $kind vus=$vus hold=${HOLD}s ..."
  if [ "$kind" = browse ] && [ "${LOAD_ENGINE:-python}" = "k6" ]; then
    # k6（Go）作为发压器：Python 版在 400 并发 TLS 长连接下会把 4 核发压机打满，
    # 测到的是发压机极限。两者的输出 JSON 同构，analyze-knee.py 通吃。
    $SSH4 "cd /root/loadtest && k6 run -e VUS=$vus -e HOLD=${HOLD}s -e BASE=$BASE -e LABEL=$FORM -e OUT=/tmp/k6.json browse-k6.js" 2>&1 | grep '^\[loadgen\]'
    $SSH4 "cat /tmp/k6.json" > "$out"
  elif [ "$kind" = browse ]; then
    $SSH4 "cd /root/loadtest && python3 loadgen.py browse --base $BASE --vus $vus --hold $HOLD --json /tmp/lg.json" 2>&1 | grep '^\[loadgen\]'
    $SSH4 "cat /tmp/lg.json" > "$out"
  else
    $SSH4 "cd /root/loadtest && python3 loadgen.py order --base $BASE --vus $vus --hold $HOLD --admin $ADMIN --product $PRODUCT --stock $STOCK --pay $PAY --secrets /root/loadtest/secrets.env --json /tmp/lg.json" 2>&1 | grep '^\[loadgen\]'
    $SSH4 "cat /tmp/lg.json" > "$out"
  fi
  echo "    -> $(basename "$out")"
}

run_matrix() {
  mkdir -p "$EV"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$EV/window-$FORM.txt"
  log "=== 形态 $FORM：浏览阶梯 ==="
  for vus in $BROWSE_TIERS; do run_load browse "$vus"; done
  log "=== 形态 $FORM：交易闭环 ==="
  for vus in $ORDER_TIERS; do run_load order "$vus"; done
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$EV/window-$FORM.txt"
  log "证据目录：$EV"
}

ACTION="${1:?usage: loadtest-suite.sh single|cluster|form <single|cluster> [tiers...]}"
if [ "$ACTION" = "form" ]; then
  FORM="$2"; set_form "$FORM"; exit 0
fi
[ "$ACTION" = "single" ] || [ "$ACTION" = "cluster" ] || { echo "unknown action: $ACTION"; exit 2; }
FORM="$ACTION"
[ $# -ge 2 ] && BROWSE_TIERS="${*:2}"
set_form "$FORM"
run_matrix
