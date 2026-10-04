# qdrant 官方镜像不带任何 HTTP 探针工具；补一个 curl 供 compose healthcheck 使用。
FROM qdrant/qdrant:v1.15.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
