#!/bin/bash
# Canal 启动前置：镜像无 envsubst，conf 目录挂载只读且单文件挂载点无法覆盖。
# 方案：模板挂到独立只读路径，注入环境变量后写入容器自身可写的 conf/。
set -e
TPL=/smartlect-canal-template.properties
DST=/home/admin/canal-server/conf/canal.properties
cp "$TPL" /tmp/canal.properties
for key in CANAL_RABBIT_HOST CANAL_RABBIT_PORT CANAL_RABBIT_VHOST CANAL_RABBIT_USER CANAL_RABBIT_PASSWORD CANAL_MYSQL_ADDRESS CANAL_MYSQL_USER CANAL_MYSQL_PASSWORD; do
  value=$(printenv "$key")
  sed -i "s/\${$key}/$value/g" /tmp/canal.properties
done
cat /tmp/canal.properties > "$DST"
# 实例模板同样注入后写入 example/（目录可写）
cp /smartlect-canal-instance-template.properties /tmp/instance.properties
for key in CANAL_MYSQL_ADDRESS CANAL_MYSQL_USER CANAL_MYSQL_PASSWORD; do
  value=$(printenv "$key")
  sed -i "s/\${$key}/$value/g" /tmp/instance.properties
done
cat /tmp/instance.properties > /home/admin/canal-server/conf/example/instance.properties

# 预声明交换机（幂等）：canal 只 publish 不 declare，Java 侧 RabbitAdmin 声明可能晚于
# canal 启动（首次部署鸡蛋顺序），404 会杀死 channel。用 bash /dev/tcp 探活 + HTTP PUT。
declare_exchange() {
  local mgmt_port="${CANAL_RABBIT_MGMT_PORT:-15672}"
  local vhost="$CANAL_RABBIT_VHOST" user="$CANAL_RABBIT_USER" pass="$CANAL_RABBIT_PASSWORD"
  local auth=$(printf '%s:%s' "$user" "$pass" | base64 2>/dev/null || echo "")
  [ -z "$auth" ] && return 0
  exec 3<>/dev/tcp/rabbitmq/"$mgmt_port" 2>/dev/null || return 0
  printf 'PUT /api/exchanges/%s/smartlect-canal HTTP/1.1\r\nHost: rabbitmq:%s\r\nAuthorization: Basic %s\r\nContent-Type: application/json\r\nContent-Length: 76\r\nConnection: close\r\n\r\n{"type":"topic","durable":true,"auto_delete":false,"internal":false,"arguments":{}}' "$vhost" "$mgmt_port" "$auth" >&3
  cat <&3 >/dev/null 2>&1
  exec 3<&- 3>&-
}
declare_exchange

exec /home/admin/app.sh
