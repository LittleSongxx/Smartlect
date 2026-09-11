# F4 有状态模拟投放合同

源码已实现，实际验收完成情况以 IMPLEMENTATION_STATUS.md 和 artifacts/f4-* 为准。

管理 API 统一 `/admin-api/assistant/ads`：GET 快照，POST `/campaigns`、`/creatives` 保存草稿，POST `/grants` 明确审批，POST `/actions` 执行1–8个动作，GET `/actions/{id}` 查回执，POST `/grants/{id}/revoke` 撤销当前授权。Java merchant cookie、`admin:legacy` 和所有写操作的同源 CSRF 都必须有效。

展示侧 GET `/api/assistant/ads/recommendations` 只返回稳定grant、ACTIVE活动/素材、余额可扣CPC且Java逐SKU复核有货的候选；读取不记曝光、不扣费。排序由 `rank_ads` 负责，`ranking_mode` 为 `ad-fatigue-pacing-v1`，逐项记 `ad_rank_score`：相关性沿用共享排序器的 `rule_score`，另按该访客对该素材的疲劳（看过未点击则降权，点过不算疲劳）与活动预算配速打分。单商家自有广告位没有竞价对手，按出价排序没有意义，所以不用CPC出价决定顺序；相关性只缩放分数，不会把合格广告排除。疲劳与配速的输入全是已记录事实（该访客自己的 `ad_interaction`/`ad_spend` 计数、活动自身 budget/spent），不读写资金权威。

用户通过 POST `/api/assistant/ads/exposures` 提交 exposure_id/creative_id，POST `/api/assistant/ads/clicks` 提交 click_id/exposure_id。主体、scope、时间、费用、产品和SKU均由服务端绑定；广告SKU是Java `propertyValueIdHash`，与product_id配对，不是推荐内部排序所用的复合key。生成或保存草稿不产生流量。实际曝光不收费，标明“模拟推广”；每个曝光最多有一个收费点击。

草稿活动固定商品/SKU和CPC价格，素材明确关联指定活动。版本从1递增，暂停、恢复、素材替换、预算与耗尽状态变动均保留版本。通用状态PATCH不存在。用户与模型都不能代替商家批准授权。

授权包含目标、商品范围、动作白名单、累计预算上限、单次预算变动上限、有效期与策略范围。请求携带当前所见 `expected_campaign_versions/expected_creative_versions`；同一事务核对本商家在批准产品范围内的全部资源，保存批准时的计划/资源快照与hash、initial_plan_id/version、envelope与hash。改变资源后必须重新查看再批准。首次批准不自动启用资源；活动和素材分别经动作启用。改变envelope必须新grant并显式指定replaces_grant_id，旧授权撤销、活动保护暂停。

预算账户只有稳定execution_scope_id对应的一个账户，period为 `scope_lifetime`，首版无自动周期清零。grant替换、plan/version、agent_run、round都不重置累计spent。reservations恒为0，因为模拟CPC立即扣费；未来预留需同一账户核算。已有账户时草稿预算也受聚合上限约束，不能用新草稿阻挡旧活动暂停。降低任何预算不能低于已花费，多活动预算变化同一事务先全检再应用，失败不发生部分预算变更。授权cap提高只能明确重新批准。

动作带action_id/idempotency_key、grant_id、plan_id/version、reason_code、evidence_ids和每个目标的expected_version。可附agent_run_id/round_id用于追踪。同请求重试返回原已提交结果；同键异参或异主体拒绝。通过/拒绝回执持久化before/after/reason；拒绝HTTP仍可GET回执。批内全检后全应用，模型后续多批计划可自行汇总真实部分成功，不能撤销已发生费用。

所有广告写操作先锁execution_scope行，随后读改账户/活动/素材；首版低流量演示用单scope锁换取简单的预算/保护竞态边界。Java网络调用在Growth事务之外。库存在查询前持久generation与请求开始时刻，返回后单独提交观察；准入年龄从开始计，最大1秒。缺行、空值、非法值、超时为unknown。Java没有库存revision；Growth generation只是本地观测顺序，不能冒充Java快照版本。

零库存观察会持久抬高pause_generation，暂停相关活动及素材；即使随后动作因授权或版本被拒绝，暂停也保留。暂停前已发出的晚到正库存不能越过栅栏；新正库存本身也不恢复投放，必须再提交显式resume并重验两级状态/授权/预算/新鲜库存。严格保证已观察售罄或暂停后的新决策停流，广告不预占库存，查询后仍可能售罄，交易仍由Java拒绝超卖。

新点击先恢复已有同键结果，再读Java库存，随后在scope事务内再次查重、验曝光归属/版本/两级资格/授权/预算/库存。一笔事务内写唯一ad_spend、累计账户/活动费用和既有AttributionStore._touch生成的AD_CLICK；origin为ads_executor，traffic_channel为AD_SIMULATED。任何失败均回滚费用和触点。已成功点击在暂停/耗尽/换素材后原样重试仍返回旧结果，不再收费；新click_id不能重扣同exposure。曝光有效期1小时。活动/素材动作来源分别保存，避免新预算动作被旧素材动作遮蔽。

归因继续F3冻结合同：广告7天、同SKU推荐24小时，锚定Java建单时间且只在订单冻结触点集合中选取；广告A买推荐B、广告后的自然回访、付款后新广告及退款继承都独立可核对。广告/推荐两维度不能相加为双份收入。模拟费用不是外部广告平台支出。
