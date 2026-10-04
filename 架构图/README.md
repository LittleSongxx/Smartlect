# Smartlect 架构图集

12 张交互式架构/流程图 + 导航站，全部锚定仓库修订 `2c8e46e`（branch `refactor/consolidation`），
由 [archify](../../) 渲染并通过 `validate / deliver / check / browser-check` 四项自动化门禁。

## 查看

本地直接打开 [`index.html`](index.html) 即可（纯静态、相对路径、自带暗色主题适配）。
每张图均可独立全屏打开（说明页有入口），支持缩放、聚焦与 PNG/SVG 导出。

## 目录

| 编号 | 图 | 类型 | 覆盖 |
|---|---|---|---|
| 01 | 系统总览 | architecture | 四层全景与信任边界 |
| 02 | 后端微服务地图 | architecture | 9 服务 · Feign 拓扑 · 分库 |
| 03 | 认证与信任边界 | architecture | Sa-Token 双账号 · 网关校验 · 内部令牌 |
| 04 | 下单到履约全链路 | sequence | Feign 编排 + 延时/死信 |
| 05 | 退款 Saga | sequence | 人工审核 + 消息闭环 |
| 06 | 秒杀抢券流程 | workflow | Redis Lua 预占 + 死信释放 |
| 07 | AI 助手内部架构 | architecture | FastAPI · LangGraph · 工具设防 |
| 08 | 导购一轮对话 | workflow | 有界 ReAct 三节点图 |
| 09 | 提案确认（人在环上） | sequence | HITL 红线与执行 |
| 10 | 知识库发布与混合检索 | dataflow | 先发布才可检索 · 双写 · RRF |
| 11 | 部署拓扑 | architecture | 宿主机进程 + Docker Compose |
| 12 | 前端双应用 | architecture | 用户端/管理端 · 共享设计令牌 |

## 结构

- `index.html` —— 图集首页（内嵌总览 + 分组导航）
- `pages/` —— 12 个组件说明页（职责、机制、证据路径、相关图交叉链接）
- `diagrams/` —— archify 候选 JSON、渲染 HTML 与各轮门禁回执
  （`review-2/3`、`width-review`、`visual-check` 为修复轮次证据）
- `build-site.py` —— 导航站生成脚本（内容改动后重跑即可）

## 重新生成

图：`node <archify>/bin/archify.mjs finalize <type> diagrams/NN-slug.json diagrams/NN-slug.html --repo-root .. --quality showcase`
站点：`python3 build-site.py`
