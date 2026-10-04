# holdout-4 独立审核与修订记录（2026-10-04）

独立审核人：独立 AI Agent（未参与起草与系统开发，只读审计）。审核维度：克隆审计（阻塞级）、金标正确性（阻塞级）、覆盖与难度、出题纪律。

## 审核结论：需修改 → 修订后通过

### 已核验通过的面

- 官方 `validate_dev_sets(split='holdout4')` 双线 PASS；导购 12 题 `satisfaction_set` 经 `sku_satisfies` 独立重推导全部一致；5→4 道空集题成因均落在 `metrics-contract.json` `empty_reasons_ok`。
- 客服全部 claims 为可见语料连续子串；10 份 `holdout4-*.md` 的 `checksum_sha256` 与文件字节一致；`allow_handoff` 组合合法；`forbidden ∩ relevant = ∅`；九折/九五折冲突进 facts 同 key 异值对；注入文档间无未标注数字矛盾；多轮题末轮自包含。

### 阻塞项（4，全部已修）

1. **shop-h4-05 与 d-06 近似克隆、硬约束与 d-56 逐字段相同** → 整题替换为 `exclude_skukey_audio`（excluded_sku_keys 音频族第二实例，dev 仅 d-71 desk 族），同时修复空集占比失衡（5/12→4/12）。
2. **sup-h4-03 与密封 holdout3 h3-01 近似克隆**（同主题同槽位同核心命题）→ 换锚为「会员日下单积分怎么用」，抵扣比例升 essential、不可兑现降 peripheral（顺带消解复合 essential 问题）。
3. **sup-h4-02 禁句「整机保修一年」有诚实答案误报面**（旧规则正文无否定前缀，评分器窗口 8 内线索词缺失时诚实引述被误杀）→ 禁句改为断言框架整句「现在仍然整机保修一年」/「整机保修一年继续有效」。
4. **sup-h4-01 金标不完整**（会员日半句由注入文档作答但未进 relevant、无 claim 覆盖）→ `relevant_doc_ids` 补 `holdout4-freight-member`，加 essential「仅限会员日当天下单的订单免基础运费」。

### 建议项（10：采纳 6，明示接受 4）

- 采纳 1：shop-h4-12 补累积 `excluded_terms:["Type-C"]` + note 反转意图。
- 采纳 2：sup-h4-12 禁句加断言框架。
- 采纳 3：shop-h4-02 note 写明与 d-66 的族内区分点。
- 采纳 5：sup-h4-10 活动名双倍→三倍积分，避开 dev d-58 同名知识点。
- 采纳 8：shop-h4-06 note 记录「有意取宽」（required 不支持 OR）。
- 采纳（随阻塞 2 消解建议 9 复合 essential）。
- 接受 4（h4-08 数量超库存空集第三例，不再增殖）、接受 6（与 h3-05 邻接但问面与锚不同）、接受 7（空集占比由阻塞 1 修复）、接受 10（与 d-01 同文档同 essential 属同族不同题）。

### 修订后复核

`validate --split holdout4` 全绿；`test_quality_v2.py` 70 项全绿（含 holdout-4 字面 + 2-gram Jaccard<0.6 双查重，对 dev/holdout1/2/3 零命中）。

### 覆盖评估（审核人原话摘要）

- 导购：机制面尚可（单金标双词、类目+词、多轮预算替换至空、注入单位伪造、双目标 compare 均为新组合，h4-01 的 259≤260 贴线设计有区分度）。
- 客服：12 题较好映射 v16 新维度（大可见池×2、难负例语料复用×5、ACL/生命周期×3、facts 冲突、多轮隐私、旧规废止、草稿泄漏均为 dev 未饱和面，h4-11 干扰文档不含金标命题、区分度真实）。
