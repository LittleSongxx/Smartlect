# smartcn 是官方中文分词插件但不随镜像分发；随镜像预装，索引 analyzer 才能生效。
FROM docker.elastic.co/elasticsearch/elasticsearch:8.19.0
RUN elasticsearch-plugin install --batch analysis-smartcn
