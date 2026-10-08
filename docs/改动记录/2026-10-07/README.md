# 2026-10-07 改动索引

本日主题：对标行业主流的六批次改造（商品搜索 ES 化、多级缓存、xxl-job、Nacos 配置中心、LiteLLM 网关、RAG 父子块）。

| 功能点 | 状态 |
| --- | --- |
| [商品搜索ES化-CanalCDC.md](商品搜索ES化-CanalCDC.md) | 批次一完成：Canal→RabbitMQ→ES 标准链路 + 87k 全量/增量索引 + 查询切 ES + 悬空链清除；端到端验证通过（搜索/增量同步/回退） |
| [商品搜索ES化-CanalCDC.md](商品搜索ES化-CanalCDC.md) | 批次二追加：多级缓存 Caffeine L1 + Redis L2 + pub/sub 失效 + Canal 兜底；35/35 + 全仓 BUILD SUCCESS |
| [xxl-job替代Scheduled.md](xxl-job替代Scheduled.md) | 批次三：xxl-job-admin 容器 + XxlJobConfig + 九任务迁移 + 全仓 BUILD SUCCESS |
| [批次四-Nacos配置中心.md](批次四-Nacos配置中心.md) | 所有 yml 推入 Nacos + nacos-config starter + spring.config.import 接入 + 全仓 BUILD SUCCESS |
| 批次五-LiteLLM.md | LiteLLM 容器部署完成；provider.py 厂商层改动过大导致测试断裂，已回退至 HEAD 干净版（303 tests OK）留待后续小步改造 |
| 批次六-RAG父子块.md | 评估后暂缓：改切分逻辑会使 v17 冻结基线失效（Recall/Faithfulness 口径变更），且批次五 provider 回退证明大文件批量替换风险高。建议独立 PR + 评测关卡 |
| [拆分订单事务边界.md](拆分订单事务边界.md) | postOrder/createConfirmed 移除 @Transactional，Feign 移出事务（五阶段重构）；幂等服务独立事务；全仓 BUILD SUCCESS |
| [Agent侧四项修正.md](Agent侧四项修正.md) | P1 预算常量统一 policy 源；P2 消融臂 DB 脱钩；P3 子智能体注入检测+截断；P4 移除 glm-5.3+成本汇总；300 tests OK |
| [部署前缺陷修复.md](部署前缺陷修复.md) | 上线前检查：九个服务 yml 重复键（SnakeYAML 2.4 下**服务启动即失败**，部署阻断）、九个 xxl-job 任务从未执行（未登记+执行器端口冲突+user 开关）、基础设施编排七处不一致（infra-up/门禁假阳性/xxljob 用户/挂载位置/健康检查/litellm/自测）、Nacos 推送自引用 |
| [线上故障-配置请求风暴.md](线上故障-配置请求风暴.md) | **线上故障（已恢复并根治）**：Nacos 客户端 3.0.3 与服务端 2.5.3 组合下配置长轮询不挂起，退化为每 200ms 短轮询 → 日志约 4GB/天 → 40G 磁盘写满 → MySQL 退出 → 站点只剩静态页。处置：清日志恢复 + 日志闸门止血 + `refreshEnabled=false` 根治（线上 120 秒窗口 data-received **8193→0**） |
| [Agent组件蓝图首批实施.md](Agent组件蓝图首批实施.md) | 蓝图 11 个工作包落地：前缀缓存重构（ADR-0014 三不变量）、记忆双时态+冲突台账（迁移 0024，ADR-0015）、close_reason 枚举、子智能体引用核验+派发审计（修死代码）、证据回查工具、预算四档分层、管理端成本/反馈/偏好历史三端点、评测 gate/probes 命令、检索词原话为主+指代补全、response_format 安全子集、漂移采样脚本；**336 单测全绿（MySQL 全开）+ 78 契约全绿**；交付后全面自查修掉 2 个正确性缺陷（turn_token_budget 误映射、指代补全词污染守卫锚定）、5 处残留（含 18 个未用 import）与 4 处文档失同步，自查整理一度引入 `_turn_tokens` 签名回归（MySQL 层当场抓回，已复测全绿，详见记录第 12 项）；⚠ 模型输入已变，官方评测需按记录内口径复跑 |
| [Agent组件对齐蓝图调研.md](Agent组件对齐蓝图调研.md) | 三方对比（本仓库 / AgentScope 版 / mewhelp）+ 四路联网调研后，产出 [Agent 组件对齐蓝图](../../agent-component-blueprint.md)：13 组件 / 6 层，逐组件给出目标设计、关键机制与参考来源；**调研与设计，未实施** |
| [README重写与展示资产更新.md](README重写与展示资产更新.md) | 参考 NewsClaw/MindCart 全面重写 README（场景小节 + 运维排查入口表 + 「没有的东西」）；架构图按当前拓扑重绘（Canal/xxl-job/Nacos 配置中心）；11 张截图全部走真实交互重拍（console 零错误，顺带跑通浏览→导购→加购→下单→支付闭环）；GitHub About 的 description/topics 从已废弃技术线全量替换 |
