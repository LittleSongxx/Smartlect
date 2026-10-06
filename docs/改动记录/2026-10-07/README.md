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
