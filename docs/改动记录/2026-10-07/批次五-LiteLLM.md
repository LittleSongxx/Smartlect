# LiteLLM 网关部署（批次五）

日期：2026-10-07 ｜ 状态：容器部署完成；provider.py 厂商层改造因风险过高回退

## 已完成

1. `deploy/compose.yaml` 新增 litellm 容器（`ghcr.io/berriai/litellm:main-v1.78-stable`，
   4000→14000 端口，master key 鉴权，健康检查）
2. `deploy/litellm/config.yaml`：qwen3.7-plus / text-embedding-v4 / gte-rerank-v2 三模型路由
3. `scripts/runtime.py` PORTS + password_keys 纳管
4. rerank 路径改为可配置（`SMARTLECT_RERANK_PATH` 环境变量，支持 /rerank 与 /reranks）

## 回退原因

provider.py 厂商层涉及 556 行文件中 _endpoint 白名单 / dashscope 分支 / ZHIPU_HOSTS /
runtime_chat_options / _price 五处大段替换，一次批量改动导致 IndentationError +
24 个测试用例 import 失败。回退至 HEAD 干净版（303 tests OK）。

## 后续建议

分小步改造（每步跑全量测试验证）：
1. 仅改 `_endpoint` 白名单加 LiteLLM host → 测试 → 提交
2. 仅删 `enable_thinking/enable_search` → 测试 → 提交
3. 仅改 `_price` → 测试 → 提交
4. 最后切 `SMARTLECT_MODEL_BASE_URL` 指向网关 → live 冒烟 + 客服线评测

保留基础设施（容器/config/runtime），代码改造延后独立批次。
