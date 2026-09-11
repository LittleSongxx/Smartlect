# ADR 0002：用决策编译表收口答 / 弃 / 转

日期：2026-09-10。状态：采用。
依据：v6/v7 开发集结构失败的三类共同根因，以及
[agent-design](../agent-design.md) 里「模型声明结构化数据、确定性代码兜住后果」。

## 问题

`FinalAnswer.answer_status` 只有 `answered|needs_human`。诉求类型（问已发布事实 /
要未发布服务 / 要例外裁决 / 明示转交 / 澄清）和本轮证据（可见且非冲突 / 合法空集 /
冲突或隔离）被压成一维。提示词只能移动阈值：漏转下降、误转上升，无法同时做对。

检索侧，模型改写常丢掉问句里的约束词（版本、原文）；合法空集被当成故障，
回退再搜并粘贴无关原文。这些都不是单题措辞问题。

## 决定

模型声明 `request_kind` 和 `handoff_requested`。控制器用同一张表编译 `answer_status` 与是否建单。
`finish_answer`、回退和空证据收口共用 `compile_decision`，不在提示词里写题面。
`handoff_requested` 与 `request_handoff` / `request_exception` 一样强制建单，这样复合「问已发布事实 + 明示转交」不必把转交挤进 `request_kind`。问工单手续本身不是转交。不加转人工短语词表。

| evidence | inquire_fact / clarify | request_service | request_exception / request_handoff |
|---|---|---|---|
| supported（本轮可见引用且非冲突） | answered，不建单 | answered | needs_human + 工单 |
| none（检索后的合法空集） | insufficient，不建单 | needs_human + 工单 | needs_human + 工单 |
| conflicting、quarantined 或 acl_denied | needs_human + 工单 | 同左 | 同左 |

`acl_denied`：同 scope 已发布且在有效期的资料盖得住问句，但对当前身份不可见，且可见块盖不住问句。
隐藏篇“盖得住”用与可见块相同的覆盖率，或问句盖住该篇标题/小标题至少一半词；正文仍不进观测。
只把 `doc_id`/`title` 交给模型，不进引用。可见块已盖住问句时，库里另有无关的更严 ACL 文不触发。
合法空集（没有任何盖得住问句的已发布文，含隐藏文也盖不住）仍不建单。

未检索（寒暄、请用户补参数）不是合法空集：`inquire_fact` / `clarify` 编译为 answered，
不建单；`request_service` / 例外 / 转交仍建单。`request_handoff` 工具路径仍直接建单。

检索把用户本轮原话放在查询前面，精排对只出现在原话里的词加权。第一次已是合法空集则
拒绝再搜。第三次检索时，若可见块仍盖不住问句约束，给模型空集观测并保留底库引用，
让它自己 `finish_answer`，不把搜爆当成故障掐死；盖得住仍触发 `retrieval_rewrite_limit`。
此时用 `store_policy` 说明缺口可以不引用那些无关篇。
回退不再为知识空集或盖不住的剩余篇粘贴原文。故障回退仍不自动开单。

不为七天无理由、次日达等题面加关键词表或固定答案。用同类、相反、未见的编译/检索单测验收。

## 后果

- schema `shopping-answer-v5`，提示 `shopping-react-v23`，Skill `support_policy` 1.5.0。
- 开发集按 revisions 校准 006/017/018/019/027/028/032 的期望。027/028/032 在主题文过期/撤回/未生效时允许 answered（不引用失效文即可），不强制 insufficient。holdout 不读不改。025/026/029/030 仍要求工单。
- 模型仍可能填错 `request_kind`；编译表只能兜住「声明 × 证据」，不能替模型理解问句。
- 编译输入输出写入只读 `decision`/`checks`，见 [ADR 0003](0003-agent-control-plane.md)。
