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
./scripts/dev.sh demo --scenario natural_assisted_purchase --seed 42
./scripts/dev.sh demo --scenario campaign_assisted_purchase --seed 42
./scripts/dev.sh demo --scenario support_refund_recovery --seed 42
./scripts/dev.sh demo --scenario purchase_stockout --seed 42
```

每次 demo 分配新的 Java 合成用户/商品/SKU；同一 scope 跨轮次累计广告费，不重置授权预算。商城首页按「为你推荐」和明确「广告/模拟推广」分区；推广曝光/点击分别记账。客服可以直接回答或转人工结束，不必为了成交继续推荐。

```bash
./scripts/dev.sh reset-demo --run-id <owned-demo-run>
./scripts/dev.sh check
./scripts/dev.sh down
```

`down` 只处理 Smartlect 自有资源。负载紧张时用 `./scripts/dev.sh apps-down` 暂停应用、保留中间件和数据。从 `apps-down` 恢复用 `up`；从 `down` 或首次启动必须先 `infra-up` 再 `up`。这些命令不停止其他项目，不删除数据卷。

## 合同与设计

[架构与 Agent 边界](docs/agent-design.md) · [交易/身份/归因](docs/contracts.md) · [投放](docs/ads-contract.md) · [经营](docs/merchant-contract.md) · [人工客服](docs/support-contract.md) · [安全重置](docs/reset-contract.md)

[运行与资源归属](docs/runtime.md) · [控制面 ADR](docs/adr/0003-agent-control-plane.md) · [决策编译 ADR](docs/adr/0002-decision-compile.md)
