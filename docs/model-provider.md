# Smartlect 模型 Provider

更新：2026-10-04。Phase3b-1 已从手写 httpx 管线迁移到 `openai==3.14.1` 官方 SDK。

## 架构

`Provider`（`assistant/src/smartlect/provider.py`）通过 `openai.AsyncOpenAI` 调用 OpenAI 兼容端点。

- **端点白名单**：仅允许 dashscope（`/compatible-mode/v1`）或智谱（`/api/paas/v4`）HTTPS 端点
- **模型白名单**：`qwen3.7-plus` / `qwen3.7-plus-2026-05-26` / `glm-5.3`
- **热切换**：MySQL `model_runtime_config` 表 + 5s TTL 异步加载，管理端可实时切 chat 模型
- **超时**：每 attempt 25s，仅 429/5xx/transport 可重试且最多 1 次
- **流式**：SDK chunk 迭代聚合，截断自动翻倍 max_tokens
- **降级**：连续失败 → 确定性收口（模板答案 / 转人工），不再自研熔断器

## ProviderChatModel（LangChain 适配器）

`agents/shopping/model_adapter.py` 把 Provider 包装为 `langchain_core.BaseChatModel`（`_agenerate` + `bind_tools`），供 `create_react_agent` 子智能体直接消费。消息在 LangChain 对象与 OpenAI wire dict 间无损往返；端点白名单、预算计数、trace 仍在 Provider 内。

## Embedding

阿里百炼 `text-embedding-v4`（1024 维，白名单硬校验），走异步索引任务；无 key 时同步发布、检索退 BM25 单路。
