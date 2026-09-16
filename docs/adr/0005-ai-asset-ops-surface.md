# ADR 0005 · AI 资产运维面（ai-ops）

日期：2026-09-16 · 状态：已实施（Phase 0-7）

## 背景

AI 资产（模型配置、提示词/技能、知识索引、Agent 留痕、工具调试）此前固化在代码、
环境变量和只写审计表里：改提示词必须发版、看 token 只能 Grafana、索引失败只能查库、
发布超过 40 条切片直接被拒。本决策新增 admin 侧「AI 资产」运维面，同时守住既有的
安全边界（模型/端点白名单、MCP 只读、提案制、知识 ACL fail-closed）。

## 决策

1. **新端点一律进 `smartlect/adminapi/` 包（APIRouter）**，app.py 只做组装，不再膨胀
   （当时已 898 行）。权限沿用 admin:legacy + CSRF，与既有管理面一致。
2. **异步索引用 app 进程内 asyncio 任务 + MySQL 任务表（`knowledge_index_job`），不引 MQ。**
   理由：Growth 单实例部署，已有 tasks/lifespan 基建；crash-safe 靠任务表 + chunk 级
   幂等（`embed_batch` 分批落库，重启续跑只补缺失切片）。规模化路径（worker 线程或
   MQ 队列）明确但不在当前规模引入——那是为不存在的并发付复杂度。
   批前 `IndexModelAudit` 照写（>4 批轮换 publication_id），致命错误中断并记
   「已成功 N/M，可续跑」。
3. **API Key 不落库。** `run/model.env`（600 权限 + 白名单键 + runtime 合并）已经是
   一套安全密钥治理；DB 只存"端点族内的激活模型选择"（`model_runtime_config`），
   Provider 加 5s TTL 的运行时解析层，空表/异常回落 env 快照。切换只允许当前
   BASE_URL 端点族可服务的模型（dashscope↔qwen 系、zhipu↔glm-5.3），跨厂商换端点
   仍是部署操作。temperature 维持代码锁 0（Agent 确定性）。
4. **Prompt/Skill 热生效，代码文本是冻结回退。** `prompt_template` 表 + 启动从代码
   常量种子（行版本从代码版本号 24/19 起续，trace 标签连续）；每次运行 SELECT 一次
   激活版本并记录 label（如 `shopping-react-v25`）。编辑仅限文本：skill 必须保持
   打包 JSON 结构 + 同 skill_id + semver，不允许新增 skill（"documents cannot install
   code"）；激活/回滚是单行原子切换，updated_by 审计。换版本应先跑 dev 评测集；
   holdout 与版本号绑定不混淆。
5. **商品知识自动导入只产 DRAFT。** Java batchDetail（清洗后字段）→ 三段式知识草稿
   （描述/参数/价格库存），覆盖式重导入（只删自动草稿，不碰 MANUAL 与已发布），
   人工核对后走正常 checksum/ACL 发布。不在导入时预嵌入：被拒草稿零向量成本。
6. **分析类功能"确定性归确定性，LLM 只做叙述"。** 评价统计（星级分布/均分/好评率/
   情绪档）与增长报告快照（attribution 支付汇总 + AI 域计数）全部代码计算；LLM 只
   基于真实数据产结构化洞察/建议，schema 门校验，失败不阻塞快照（mock 模式可用）。
7. **运行浏览器不查 message 表。** agent_run/tool_call/agent_run_event 按范围过滤 +
   字段白名单；context 只暴露运维键，其余键名在 `context_hidden_keys` 透明列出；
   30 天 purge 后的空上下文如实标注。工具调试台只开只读且无归因副作用的工具
   （+ catalog_search 直连检索层探针），每次调用本身是一次留痕运行。

## 已知边界 / 延后项

- **growth-console.scss 未退役**：四个 AI 经营页（Merchant/Ads/Knowledge/Support）的
  原生表单体保留，仅页头统一为 PageHeader。理由：这四页承载最重的业务约束与
  900+ 行断言级测试，纯美学重写带来回归风险而无功能收益；待下一轮专项处理。
- 运行浏览器按需查询，未给 agent_run 的 created_at 之外的维度建复合索引；
  数据量上来后再按查询画像加。
- 评测：本次各阶段以单测 + MySQL 契约锁行为；dev 评测集回归在接入真实栈后执行
  （holdout 不动）。
