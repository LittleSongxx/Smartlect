#!/usr/bin/env bash
# 把应用运行时分发到副本节点（node1 执行）
#
# 副本节点不承载中间件，只需要：同一份 scripts/、同一份 JAR、一份**本机定制**的 runtime.env。
# JAR 从 node1 已构建好的产物直接取，副本节点不装 Maven 也不编译。
#
# 用法：bash sync-app-node.sh node2 "gateway,product,order,user"
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SMARTLECT_ROOT:-/opt/smartlect}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
log() { echo "[sync-app $(date +%T)] $*"; }

TAG="${1:?usage: sync-app-node.sh <node2|node3> <svc,svc,...>}"
SERVICES="${2:?usage: sync-app-node.sh <node2|node3> <svc,svc,...>}"
case "$TAG" in
  node2) IP="$NODE2_IP" ;;
  node3) IP="$NODE3_IP" ;;
  *) echo "unknown node tag: $TAG"; exit 2 ;;
esac
SSH="ssh $CLUSTER_SSH_OPTS root@$IP"
SCP="scp $CLUSTER_SSH_OPTS"

log "preparing layout on $IP ..."
$SSH "mkdir -p $ROOT/{scripts,run/logs,run/cache,run/apps,backend} $ROOT/run/uploads"

log "syncing scripts/ ..."
rsync -a --delete -e "ssh $CLUSTER_SSH_OPTS" "$ROOT/scripts/" "root@$IP:$ROOT/scripts/"

# 服务 → 产物目录：admin/gateway 在模块根的 target/，其余在 app/target/
artifact_dir() { case "$1" in admin|gateway) echo "$ROOT/backend/smartlect-$1/target" ;; *) echo "$ROOT/backend/smartlect-$1/app/target" ;; esac; }

for svc in ${SERVICES//,/ }; do
  dir="$(artifact_dir "$svc")"
  jars=("$dir"/smartlect-"$svc"-*.jar)
  [ "${#jars[@]}" -eq 1 ] || { echo "expected exactly one JAR for $svc in $dir, found ${#jars[@]}"; exit 1; }
  log "  $svc -> $(basename "${jars[0]}") ($(du -h "${jars[0]}" | cut -f1))"
  $SSH "mkdir -p $dir"
  # --delete 保证目标目录只留当前版本的 JAR：app_launch 要求 glob 恰好命中一个
  rsync -a --delete -e "ssh $CLUSTER_SSH_OPTS" --include='smartlect-*.jar' --exclude='*' "$dir/" "root@$IP:$dir/"
done

log "syncing runtime.env ..."
$SCP "$ROOT/run/runtime.env" "root@$IP:$ROOT/run/runtime.env"
$SSH "chmod 600 $ROOT/run/runtime.env"

log "rendering node-specific overrides into runtime.env ..."
# 副本节点的差异只有三处：本机跑哪些服务、绑哪个地址、注册哪个 IP。
# 其余（集群中间件地址、密钥）与 node1 完全一致。
$SSH "python3 - \"$ROOT/run/runtime.env\" '$IP' '$SERVICES' <<'PY'
import sys
path, ip, services = sys.argv[1], sys.argv[2], sys.argv[3]
overrides = {
    'SMARTLECT_APP_SERVICES': services,
    'SMARTLECT_APP_BIND_ADDRESS': '0.0.0.0',
    'SMARTLECT_APP_REGISTER_IP': ip,
    'SMARTLECT_PROJECT_FOLDER': '/opt/smartlect/run/uploads/',
}
# 刻意不在这里写 JVM/连接池数值：这些参数跟着机器规格走，由 apply-sizing.sh 按
# nproc 与本机角色推导。写死过一次（2 核时代的 1 处理器/320m），扩容后被本脚本
# 原样同步回来覆盖掉新值——正是"硬编码会漂移"的现场。
lines = [line for line in open(path).read().splitlines()
         if line and line.split('=', 1)[0] not in overrides]
lines += [f'{k}={v}' for k, v in overrides.items()]
open(path, 'w').write('\n'.join(lines) + '\n')
print('overrides applied:', ', '.join(sorted(overrides)))
PY
chmod 600 $ROOT/run/runtime.env"

log "installing systemd unit ..."
$SCP "$HERE/../app-node/smartlect-apps.service" "root@$IP:/etc/systemd/system/smartlect-apps.service"
$SSH "systemctl daemon-reload && systemctl enable smartlect-apps >/dev/null 2>&1 && echo '  unit enabled'"

log "applying spec-derived sizing (JVM/pool) ..."
$SCP "$HERE/apply-sizing.sh" "root@$IP:/opt/cluster/apply-sizing.sh"
$SSH "bash /opt/cluster/apply-sizing.sh"

log "sync-app-node $TAG complete: $SERVICES"
