<p align="center">
  <img src="docs/assets/logo.svg" alt="Smartlect" width="120" />
</p>

<h1 align="center">Smartlect</h1>

<p align="center">
  <b>一家会按商品回答的店</b><br/>
  C 端商城 + 商家后台，中间只放一个 Shopping Agent
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Vue-3-42b883?style=flat-square&logo=vuedotjs&logoColor=white" />
  <img src="https://img.shields.io/badge/Java-17-orange?style=flat-square&logo=openjdk&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-bounded-1a1a2e?style=flat-square" />
  <img src="https://img.shields.io/badge/Spring_Cloud-2025-6db33f?style=flat-square&logo=springboot&logoColor=white" />
  <img src="https://img.shields.io/badge/MySQL-8-4479a1?style=flat-square&logo=mysql&logoColor=white" />
  <a href="https://github.com/LittleSongxx/Smartlect/actions/workflows/ci.yml"><img src="https://github.com/LittleSongxx/Smartlect/actions/workflows/ci.yml/badge.svg" /></a>
</p>

<p align="center">
  <img src="docs/assets/screenshots/product-guide.png" alt="商品页智能导购：正在问本商品，并对照两个规格" width="100%" />
</p>

---

**Smartlect 是我做的一套可演示单店：前面是能逛的商城，后面是商家后台，中间只有一个 Shopping Agent。** 商品页默认「正在问本商品」，检索的是这件的资料和店规，不是整站闲聊。店规和商品说明可以在后台写成文档、发布后再被引用；价格和库存不进向量，下单、退款都要你点确认。Java 是交易权威，Python 只通过受控 API 说话。

线上可以直接点：[用户端](http://39.107.102.244/) · [管理端](http://39.107.102.244/admin/)。支付和广告花费是模拟的，没有真实资金。

**对外试用账号是公开的，权限在服务端按身份拒绝。** 不要用仓库或环境里的超管、也不要用 `9100000000` 那组内部演示买家。

| 端 | 账号 | 密码 | 能做什么 | 不能做什么 |
| --- | --- | --- | --- | --- |
| 用户端 | `visitor@smartlect.demo` | `Visit-Smartlect-2026` | 逛店、看商品、问导购 | 下单、加购、改密、改地址、注册新号 |
| 管理端 | `gallery` | `Visit-Smartlect-2026` | 看看板、商品、订单、知识库和经营数据 | 改库存、发知识、发券、发货、管账号、看用户隐私 |

---

## 它每天在做什么

<table>
<tr>
<td width="33%" valign="top">

**① 逛店**

首页、分类、搜索、商品详情都是一家真店的皮。货架、价格、库存来自 Java 目录，不是为聊天临时拼的卡片。

</td>
<td width="33%" valign="top">

**② 问这件**

在商品页打开导购，范围钉在「正在问本商品」。Shopping Agent 按这件检索已发布资料；答不上来就承认，而不是改口吹下一件。

</td>
<td width="33%" valign="top">

**③ 管店**

后台维护店规和商品资料，看经营助手给出的下一轮计划。授权范围里可以执行，越界要再批准一次。

</td>
</tr>
</table>

<p align="center">
  <img src="docs/assets/screenshots/home.png" alt="智选商城首页" width="100%" />
  <em>C 端先是一家店：分类、广告位、智选好物，导购是店里的入口，不是站外机器人。</em>
</p>

---

## 它怎么分层

```
                 ┌────────────────── Vue 用户端 / 商家后台 ──────────────────┐
                 │   逛店 · 商品 · 导购浮层          知识库 · 经营 · 商品编辑   │
                 └────────────────────────────┬─────────────────────────────┘
                                              │ 只展示，不写交易
┌─────────────────────────────────────────────▼─────────────────────────────────────────────┐
│                              Gateway · 鉴权，把登录态收成可信身份                              │
└─────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                              │
┌─────────────────────────────────────────────▼─────────────────────────────────────────────┐
│                         Python Growth · FastAPI + LangGraph                               │
│     Shopping Agent（有界 ReAct）          Merchant Agent（计划 → 执行 → 再计划）            │
│     RAG / 推荐 / 账本是确定性服务          价格、库存不进向量                                 │
└─────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                              │ 用户确认后的受控 API
┌─────────────────────────────────────────────▼─────────────────────────────────────────────┐
│                      Java · 9 个 Spring Cloud 服务，交易库只由这里写                         │
│                         价格 / 库存 / 订单 / 支付 / 退款                                     │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

浏览器只负责把状态画出来。Gateway 做身份。Python 负责「问什么、检索什么、下一步计划什么」。真正改价格、扣库存、落订单的，只有 Java。

---

## 能力地图

<table>
<tr>
<td width="50%"><img src="docs/assets/screenshots/home.png" alt="用户端首页" /><br/><b>逛店</b> — 首页就是货架，不是 Agent 控制台套了个商城皮</td>
<td width="50%"><img src="docs/assets/screenshots/product-guide.png" alt="商品页导购" /><br/><b>问这件</b> — 浮层默认「正在问本商品」，规格对照来自这一次真实提问</td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/screenshots/assistant.png" alt="独立导购页" /><br/><b>独立导购</b> — 不在商品页时按全店政策聊运费、退换和选品</td>
<td width="50%"><img src="docs/assets/screenshots/category.png" alt="分类页" /><br/><b>分类</b> — 49 个类目可以点进去逛，搜索走同一套在售目录</td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/screenshots/admin-knowledge.png" alt="管理端知识库" /><br/><b>知识库</b> — 店规写成可发布的文档；撤回后不再被新的客服引用</td>
<td width="50%"><img src="docs/assets/screenshots/admin-merchant.png" alt="经营助手" /><br/><b>经营助手</b> — 先看点击、费用和净成交，再决定下一轮做不做</td>
</tr>
</table>

---

## 技术栈

| | |
|---|---|
| **前端** | Vue 3 · Vite · Element Plus · 用户端 + 管理端 |
| **交易** | Java 17 · Spring Boot 3.5 · Spring Cloud · 9 个服务 |
| **增长** | Python 3.11 · FastAPI · LangGraph |
| **存储** | MySQL · Redis · RabbitMQ · Nacos |
| **模型** | 独立配置；演示走 live，缺配置时明确失败 |

```
backend/   gateway · user · product · stock · cart · order · pay · coupon · admin
growth/    Shopping / Merchant Agent · RAG · 推荐 · 知识库 · 经营
web/       用户端与管理端（Vue 3）
evals/     quality-v2（导购 / 客服 / 投放）
docs/      设计说明与合同，给想往下翻的人
```

---

## 快速开始

本地看演示：

```bash
./scripts/dev.sh bootstrap
./scripts/dev.sh build
./scripts/dev.sh infra-up
./scripts/dev.sh up
```

用户端 [http://127.0.0.1:18180/](http://127.0.0.1:18180/) ，管理端 [http://127.0.0.1:18181/admin/](http://127.0.0.1:18181/admin/) 。需要一套示例货架时再执行 `./scripts/dev.sh seed-store`。

已经部署的副本：[用户端](http://39.107.102.244/) · [管理端](http://39.107.102.244/admin/)。试用账密见上文，超管密码不在此公开。

边界、评测和运行细节在 [docs/](docs/)： [Agent 设计](docs/agent-design.md) · [quality-v2](docs/quality-eval-v2.md) · [本地运行](docs/runtime.md)。

## 质量

仓库带 [CI](https://github.com/LittleSongxx/Smartlect/actions/workflows/ci.yml)。公开评测是 [quality-v2](docs/quality-eval-v2.md) 三条线（导购 / 客服 / 投放），每条自己的指标和分母，不合成总分。

```bash
./scripts/dev.sh check
```

---

## 许可

仓库根目录**没有** `LICENSE` 文件。`backend/`、`web/user/`、`web/admin/` 以及 `growth/licenses/` 下的子模块各自为 **MIT**。
