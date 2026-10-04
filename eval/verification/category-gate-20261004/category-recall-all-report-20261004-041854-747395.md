# 品类知识库召回评测报告（2026-10-04 04:19:23）

标注集 `eval/category_recall.jsonl`，正例 41 条。标注单位为知识文档名。

| 指标 | 值 | 阈值 |
|---|---|---|
| Recall@3 | 0.927 | ≥ 0.85（阻断） |
| Precision@3 | 0.358 | 观察项（未穷举金标，不阻断） |
| MRR | 0.772 | ≥ 0.85（阻断） |
| R@1（首位命中） | 0.512 | 观察项 |
| NDCG@3 | 0.794 | ≥ 0.85（阻断） |
| 不可回答准确率 | 0.000 | ≥ 1.0（阻断） |
| 政策拒答准确率 | 1.000 | ≥ 1.0（阻断） |

门禁结论：**BLOCK**

未达标项：
- MRR 0.7724 < 0.85
- NDCG@3 0.7941 < 0.85
- 无结果准确率 0.0 < 1.0

| query | 类型 | Recall | R@1 | Precision | MRR | NDCG | 召回文档 | 标注文档 |
|---|---|---|---|---|---|---|---|---|
| 旅行装备选购的整体思路是什么 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | travel-gear.md,eval-travel-gear-概览.md,eval-travel-gear-价格与预算.md | eval-travel-gear-概览.md |
| 数码配件要怎么判断参数好坏 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | digital-accessories.md,eval-digital-accessories-参数判断.md,eval-digital-accessories-概览.md | eval-digital-accessories-参数判断.md |
| 家居生活选购有哪些常见的坑 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | home-living.md,eval-home-living-避坑与合规.md,eval-home-living-概览.md | eval-home-living-避坑与合规.md |
| 户外运动的价格与预算怎么看 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | outdoor-sports.md,eval-outdoor-sports-价格与预算.md,eval-outdoor-sports-概览.md | eval-outdoor-sports-价格与预算.md |
| 美妆个护看参数主要看哪些 | single | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-beauty-care-参数判断.md,eval-beauty-care-概览.md,eval-beauty-care-避坑与合规.md | eval-beauty-care-参数判断.md |
| 厨房餐饮要避开什么坑 | single | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-kitchen-dining-避坑与合规.md,eval-kitchen-dining-概览.md,eval-kitchen-dining-价格与预算.md | eval-kitchen-dining-避坑与合规.md |
| 办公学习用品怎么选总述 | single | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-office-study-概览.md,eval-office-study-避坑与合规.md,eval-office-study-价格与预算.md | eval-office-study-概览.md |
| 母婴宠物的价格预算注意什么 | single | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-baby-pet-价格与预算.md,eval-baby-pet-概览.md,eval-baby-pet-参数判断.md | eval-baby-pet-价格与预算.md |
| 旅行装备的参数口径怎么统一 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | travel-gear.md,eval-travel-gear-参数判断.md,eval-travel-gear-概览.md | eval-travel-gear-参数判断.md |
| 厨房餐饮选购的总体判断顺序 | single | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-kitchen-dining-概览.md,eval-kitchen-dining-参数判断.md,eval-kitchen-dining-价格与预算.md | eval-kitchen-dining-概览.md |
| 数码配件有哪些合规风险 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | digital-accessories.md,eval-digital-accessories-避坑与合规.md,eval-digital-accessories-参数判断.md | eval-digital-accessories-避坑与合规.md |
| 家居生活的到手价怎么估 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | home-living.md,eval-home-living-价格与预算.md,eval-home-living-概览.md | eval-home-living-价格与预算.md |
| 户外运动新手入门怎么开始 | single | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | outdoor-sports.md,eval-outdoor-sports-概览.md,eval-outdoor-sports-避坑与合规.md | eval-outdoor-sports-概览.md |
| 厨房用品和户外装备的选购思路分别是什么 | cross | 0.50 | 0.50 | 0.33 | 1.00 | 0.38 | eval-outdoor-sports-概览.md,eval-travel-gear-概览.md,outdoor-sports.md | eval-kitchen-dining-概览.md,eval-outdoor-sports-概览.md |
| 数码配件和办公学习用品的参数判断有什么不同 | cross | 0.50 | 0.00 | 0.33 | 0.50 | 0.48 | digital-accessories.md,eval-digital-accessories-参数判断.md,eval-digital-accessories-概览.md | eval-digital-accessories-参数判断.md,eval-office-study-参数判断.md |
| 旅行装备和家居用品的预算口径差别在哪 | cross | 0.50 | 0.00 | 0.33 | 0.50 | 0.48 | travel-gear.md,eval-travel-gear-价格与预算.md,eval-travel-gear-概览.md | eval-travel-gear-价格与预算.md,eval-home-living-价格与预算.md |
| 美妆个护和母婴用品各有什么坑要注意 | cross | 1.00 | 0.50 | 0.67 | 1.00 | 1.00 | eval-beauty-care-避坑与合规.md,eval-baby-pet-避坑与合规.md,eval-beauty-care-概览.md | eval-beauty-care-避坑与合规.md,eval-baby-pet-避坑与合规.md |
| 数码配件与旅行装备的隐性成本分别是什么 | cross | 0.50 | 0.00 | 0.33 | 0.33 | 0.38 | digital-accessories.md,travel-gear.md,eval-digital-accessories-价格与预算.md | eval-digital-accessories-价格与预算.md,eval-travel-gear-价格与预算.md |
| 家居和厨房用品比参数时注意什么 | cross | 0.50 | 0.50 | 0.33 | 1.00 | 0.76 | eval-home-living-参数判断.md,eval-home-living-概览.md,eval-home-living-避坑与合规.md | eval-home-living-参数判断.md,eval-kitchen-dining-参数判断.md |
| 办公学习与数码配件的入门步骤分别怎么走 | cross | 0.50 | 0.00 | 0.33 | 0.50 | 0.48 | digital-accessories.md,eval-office-study-概览.md,eval-office-study-价格与预算.md | eval-office-study-概览.md,eval-digital-accessories-概览.md |
| 户外和旅行装备的合规风险清单分别有哪些 | cross | 1.00 | 0.00 | 0.67 | 0.50 | 0.67 | travel-gear.md,eval-outdoor-sports-避坑与合规.md,eval-travel-gear-避坑与合规.md | eval-outdoor-sports-避坑与合规.md,eval-travel-gear-避坑与合规.md |
| 母婴和美妆产品看规格参数的差异 | cross | 1.00 | 0.50 | 0.67 | 1.00 | 0.86 | eval-beauty-care-参数判断.md,eval-baby-pet-参数判断.md,eval-beauty-care-避坑与合规.md | eval-baby-pet-参数判断.md,eval-beauty-care-参数判断.md |
| 除了标价，买个行李箱还有哪些看不见的花销 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-travel-gear-价格与预算.md,travel-gear.md,eval-digital-accessories-价格与预算.md | eval-travel-gear-价格与预算.md |
| 宣传页一堆参数看得眼晕，哪些才是真的有用 | paraphrase | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | eval-beauty-care-参数判断.md,eval-digital-accessories-参数判断.md,eval-office-study-参数判断.md | eval-digital-accessories-参数判断.md |
| 网上买易碎的东西，出了纠纷怎么举证 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-home-living-避坑与合规.md,eval-travel-gear-避坑与合规.md,eval-beauty-care-参数判断.md | eval-home-living-避坑与合规.md |
| 第一次玩露营，从哪几步开始入手 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-outdoor-sports-概览.md,eval-travel-gear-概览.md,outdoor-sports.md | eval-outdoor-sports-概览.md |
| 护肤品的到手成本里容易被忽略的是什么 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-beauty-care-价格与预算.md,eval-travel-gear-价格与预算.md,eval-digital-accessories-价格与预算.md | eval-beauty-care-价格与预算.md |
| 厨房用具收到有问题，售后该怎么留证据 | paraphrase | 1.00 | 0.00 | 0.33 | 0.33 | 0.50 | eval-kitchen-dining-参数判断.md,eval-home-living-避坑与合规.md,eval-kitchen-dining-避坑与合规.md | eval-kitchen-dining-避坑与合规.md |
| 买台灯这些桌面物件怎么绕开虚标 | paraphrase | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | eval-office-study-避坑与合规.md,eval-office-study-参数判断.md,eval-home-living-参数判断.md | eval-office-study-参数判断.md |
| 刚有娃，买婴儿用品从哪儿开始下手 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-baby-pet-概览.md,eval-baby-pet-避坑与合规.md,eval-baby-pet-价格与预算.md | eval-baby-pet-概览.md |
| 出远门背东西，钱主要该花在哪些属性上 | paraphrase | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | eval-travel-gear-价格与预算.md,eval-travel-gear-概览.md,travel-gear.md | eval-travel-gear-概览.md |
| 充电器这类东西跨境买要注意什么风险 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-digital-accessories-避坑与合规.md,digital-accessories.md,eval-office-study-避坑与合规.md | eval-digital-accessories-避坑与合规.md |
| 大件家具寄回家，实际要花的钱怎么算 | paraphrase | 1.00 | 0.00 | 0.33 | 0.50 | 0.63 | eval-policy-global-shipping.md,eval-home-living-价格与预算.md,cross-border-guide.md | eval-home-living-价格与预算.md |
| 装备的承重防水这些数字怎么看才不被忽悠 | paraphrase | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-outdoor-sports-参数判断.md,eval-travel-gear-参数判断.md,eval-outdoor-sports-概览.md | eval-outdoor-sports-参数判断.md |
| 美国方向的免税额度是多少，超过怎么算 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-us.md,cross-border-guide.md,eval-policy-cn.md | eval-policy-us.md |
| 欧洲方向包裹的申报有什么要求 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-eu.md,eval-travel-gear-避坑与合规.md,eval-policy-battery.md | eval-policy-eu.md |
| 寄日本的运费和体积重怎么算 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-jp.md,eval-policy-global-shipping.md,cross-border-guide.md | eval-policy-jp.md |
| 新加坡方向清关要注意什么 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-sg.md,eval-travel-gear-避坑与合规.md,cross-border-guide.md | eval-policy-sg.md |
| 中国跨境零售哪些品类可以买 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-cn.md,cross-border-guide.md,eval-policy-battery.md | eval-policy-cn.md |
| 跨境运费按什么规则计价 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-global-shipping.md,cross-border-guide.md,eval-policy-cn.md | eval-policy-global-shipping.md |
| 带电池的商品能寄国外吗 | policy_refusal | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | eval-policy-battery.md,eval-travel-gear-避坑与合规.md,cross-border-guide.md | eval-policy-battery.md |


## 执行证据

- 选集：`all`，50/50 条；完整选集：True。
- 选集内容 SHA-256：`571d8a4b240dcc0e202577eeecf8a241aaa16a770457dd94a654682cce7f73b5`。
- 工作区内容 SHA-256：`87fef943ad3ed244209106201c24acc4b34788ed281d4312cea351c7111d114e`（包含未提交源文件；详细范围见同名 manifest）。
- 执行状态：**COMPLETED**；门禁：**BLOCK**；门禁范围：`diagnostic`。
- 实际策略：`["category_vector_document_scope_v1"]`。
- 模型、Prompt、数据文件、依赖版本及逐项 hash 均保存在同名 `.manifest.json`。
