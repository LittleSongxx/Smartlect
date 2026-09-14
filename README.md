# Smartlect

独立单店 AI 导购、RAG 客服与模拟经营闭环。

Java 是价格、库存、订单、支付和退款的唯一权威；Python Growth 通过受控 API 与业务事件接入，不直改交易表。用户确认具体交易后才落单；商家首次批准稳定授权范围，后续经营计划在范围内执行，越界重新批准。

## 系统是什么

- **Java 电商底座**：价格、库存、订单、支付、退款与归因在交易侧落库；幂等与金额以 Java 为准。
- **Python Growth**：两个领域 Agent——Shopping 是有界 ReAct，Merchant 是观察→计划→授权内执行→等待新观测后再规划。没有总 Supervisor，也没有意图分类器把控制权交给模型。
- **确定性服务**：推荐、RAG 检索、投放保护、归因和确认执行不额外包装成 Agent。只读 MCP 复用同一套工具与权限，不暴露写工具。
- **两端界面**：用户端是商城首页、浏览、导购/客服、商品与订单；管理端是活动授权、经营助手、知识库与人工客服。刷新不重放写操作。终答与经营 run 附带只读决策快照，不改变编译或授权。

支付与广告费用均为本地模拟，没有接入真实资金或对外投放。

## 本地运行

需要 JDK 17+、Maven、Python 3.11+、Node/npm 和 Docker Compose。默认 loopback 端口避让其他项目：用户端 `18180`，管理端 `18181/admin/`，网关以 `./scripts/dev.sh status` 为准。

```bash
./scripts/dev.sh bootstrap
./scripts/dev.sh build
./scripts/dev.sh infra-up
./scripts/dev.sh up
./scripts/dev.sh status
./scripts/dev.sh apps-check
```

`bootstrap` 保留已有配置，只在 Git 忽略的 `run/runtime.env` 生成本项目业务凭证。模型白名单放在权限 600、同样被忽略的 `run/model.env`；默认 `qwen3.7-plus`，不自动更换旗舰模型。启用 live 会产生供应商费用，字段与模式见 [模型说明](docs/model-provider.md)。缺配置时 live 明确失败；mock、live 和规则回退分别标记。

```bash
./scripts/dev.sh seed-store
./scripts/dev.sh demo --seed 42
```

`seed-store` 准备默认门店（知识、广场券与导购剧本，只写 `execution_scope_id=store`），让用户端开箱可看推荐与广告分区、可演示政策问答与下单。`demo` 跑交易回归：首次初始化合成用户/商品/SKU 后覆盖下单、幂等重放、支付、退款、售罄与取消对账；事件消费启用时等待增长账本收齐。商城首页按「为你推荐」和明确「广告/模拟推广」分区；推广曝光/点击分别记账。客服可以直接回答或转人工结束，不必为了成交继续推荐。

```bash
./scripts/dev.sh reset-demo --run-id <owned-demo-run>
./scripts/dev.sh check
./scripts/dev.sh down
```

`down` 只处理 Smartlect 自有资源。负载紧张时用 `./scripts/dev.sh apps-down` 暂停应用、保留中间件和数据。从 `apps-down` 恢复用 `up`；从 `down` 或首次启动必须先 `infra-up` 再 `up`。这些命令不停止其他项目，不删除数据卷。

## 质量评测

唯一评测体系是 [quality-v2](docs/quality-eval-v2.md)：导购选品、政策客服、广告投放三条线。公开指标为导购 `Pass@1` 与 `Precision@4/ceiling`、客服 `Recall@8` 与 judge 判分的 `Faithfulness`、广告 `Attribution_integrity`，每指标印分母与 Wilson 95% CI，不合成总分。`--trials N` 支持逐题多次试验与 `pass^k` 方差；LLM judge 与主模型不同源，并经 32 对已知判定校准集与双 judge 交叉验证。开发集为导购 65 例、客服 63 例、广告 12 剧本；合同测试 68 项。禁句/禁文档走确定性规则门，不交给 judge。

## 合同与设计

[架构与 Agent 边界](docs/agent-design.md) · [交易/身份/归因](docs/contracts.md) · [投放](docs/ads-contract.md) · [经营](docs/merchant-contract.md) · [人工客服](docs/support-contract.md) · [安全重置](docs/reset-contract.md)

[运行与资源归属](docs/runtime.md) · [控制面 ADR](docs/adr/0003-agent-control-plane.md) · [决策编译 ADR](docs/adr/0002-decision-compile.md)
