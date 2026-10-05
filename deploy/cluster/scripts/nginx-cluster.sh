#!/usr/bin/env bash
# nginx 网关多后端（node1 执行）
#
# 把 /api/ 从写死的 127.0.0.1:18080 改成三节点网关 upstream，带被动健康检查
# （max_fails/fail_timeout）与 keepalive。副本节点网关挂掉时 nginx 自动摘除，
# 不需要人工介入。可逆：apply 前先备份，revert 直接还原备份。
#
# 用法：bash nginx-cluster.sh apply | revert | status
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
CONF="${NGINX_CONF:-/etc/nginx/sites-available/smartlect-app}"
BACKUP="$CONF.pre-cluster"
GATEWAY_PORT="${GATEWAY_PORT:-18080}"

apply() {
  if grep -q "upstream smartlect_gateway" "$CONF"; then
    echo "[nginx] upstream already present; nothing to do"
    return 0
  fi
  [ -f "$BACKUP" ] || cp -p "$CONF" "$BACKUP"
  python3 - "$CONF" "$GATEWAY_PORT" "$NODE1_IP" "$NODE2_IP" "$NODE3_IP" <<'PY'
import sys
path, port = sys.argv[1], sys.argv[2]
ips = sys.argv[3:]
text = open(path).read()
upstream = ("# 集群期网关多实例（deploy/cluster/scripts/nginx-cluster.sh 注入）\n"
            "upstream smartlect_gateway {\n"
            + "".join(f"    server {ip}:{port} max_fails=3 fail_timeout=10s;\n" for ip in ips)
            + "    keepalive 64;\n}\n\n")
text = upstream + text
before = "proxy_pass http://127.0.0.1:%s;" % port
after = "proxy_pass http://smartlect_gateway;"
assert text.count(before) == 1, f"expected exactly one '{before}', found {text.count(before)}"
text = text.replace(before, after)
open(path, "w").write(text)
print("[nginx] injected upstream with backends:", ", ".join(ips))
PY
}

revert() {
  if [ -f "$BACKUP" ]; then
    cp -p "$BACKUP" "$CONF"
    echo "[nginx] restored $BACKUP"
  else
    python3 - "$CONF" "$GATEWAY_PORT" "$NODE1_IP" <<'PY'
import re, sys
path, port, node1 = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read()
text = re.sub(r"# 集群期网关多实例.*?\n\n", "", text, flags=re.S)
text = text.replace("proxy_pass http://smartlect_gateway;", f"proxy_pass http://127.0.0.1:{port};")
open(path, "w").write(text)
PY
    echo "[nginx] upstream removed (no backup found)"
  fi
}

status() {
  nginx -T 2>/dev/null | sed -n '/upstream smartlect_gateway/,/}/p'
  nginx -T 2>/dev/null | grep -n "proxy_pass http://smartlect_gateway" || echo "(upstream not referenced)"
}

case "${1:?usage: nginx-cluster.sh apply|revert|status}" in
  apply)  apply;  nginx -t && systemctl reload nginx && echo "[nginx] reloaded";;
  revert) revert; nginx -t && systemctl reload nginx && echo "[nginx] reloaded";;
  status) status;;
  *) echo "unknown action: $1"; exit 2;;
esac
