#!/usr/bin/env bash
# 修复 VPC 与 Docker 默认网桥的子网重叠（node1/node2/node3 执行）
#
# 现象：发压机 NewsClaw 内网 172.17.40.108 与集群双向不通（连 ICMP 都不通），
# 而集群三节点之间互通正常。
# 根因：阿里云 VPC 网段是 172.16.0.0/12，与 Docker 默认网桥 docker0 的
# 172.17.0.0/16 重叠；docker0 的内核路由 172.17.0.0/16 比 VPC 的缺省路由更具体，
# 于是发往 172.17.x.x 的包全被丢进 linkdown 的 docker0，回包根本出不了网卡。
#       $ ip route get 172.17.40.108
#       172.17.40.108 dev docker0 src 172.17.0.1      ← 走错网卡
#
# 处置：为发压机地址补一条 /32 主机路由，经 eth0 的真实网关转发。
# /32 比 /16 更具体，优先生效；只影响这一个地址，不动 docker0，也不重启任何容器。
#
# 长期建议（未执行，见改动记录"未完成项"）：把 VPC 内实例迁到不与 172.17.0.0/16
# 重叠的交换机，或把 docker0 的默认网段改成 172.30.0.0/16（需重启 Docker）。
set -euo pipefail
PEER="${1:?usage: fix-vpc-route.sh <peer-ip>}"
UNIT=/etc/systemd/system/smartlect-vpc-route.service

GATEWAY=$(ip route | awk '/^default/ {print $3; exit}')
[ -n "$GATEWAY" ] || { echo "no default gateway found"; exit 1; }

echo "[vpc-route] $(hostname): $PEER/32 via $GATEWAY dev eth0"
ip route replace "$PEER/32" via "$GATEWAY" dev eth0

cat > "$UNIT" <<EOF
# 与 Docker 默认网桥重叠的 VPC 对端地址（见 deploy/cluster/scripts/fix-vpc-route.sh）。
# 由 DHCP 下发的缺省路由在重启后重建，这条主机路由必须同样在启动时重建。
[Unit]
Description=Smartlect VPC peer route (overrides docker0 shadowing)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/ip route replace $PEER/32 via $GATEWAY dev eth0
ExecStop=/sbin/ip route del $PEER/32

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now smartlect-vpc-route.service >/dev/null 2>&1
echo "[vpc-route] route installed and persisted:"
ip route get "$PEER"
