# RAG 父子块评估结论（批次六）

日期：2026-10-07 ｜ 状态：评估后暂缓实施

## 评估结论

当前 83 题客服线 Recall@3 95.7% / Faithfulness 95.5%（RAGAS 口径）已经优秀，
引入父子块（small-to-big）的边际收益不确定，而风险明确：

1. **评测基线失效**：切分逻辑变更使 LEXICAL_VERSION / RERANK_VERSION /
   index_version 全部失效 → 必须重建索引 + 重跑 83 题 × 3 试验完整评测，
   且新口径与 v17 冻结基线不可直接对比（改了实验条件）
2. **引用校验链断裂**：`_validate_citations` 按子块 content/offset/checksum 校验，
   父子块模式下 citations 需改指父块，校验语义需同步重设计
3. **大文件改动风险**：knowledge.py 1000+ 行，切分/检索/组装/citation 四链路联动，
   批次五 provider.py（556 行）批量替换已证明此类改动在此工程节奏下不可控

## 主流对齐确认

当前 RAG 栈（Hybrid Search + RRF + Rerank + 知识治理 + 引用溯源）已与 2026
生产级标准完全对齐（批次一调研结论）。父子块是"可选升级"而非"落后差距"，
在当前指标已优秀的前提下，收益/风险比不支持立即实施。

## 建议实施时机

- 客服线 Recall 或 Faithfulness 出现系统性下降时（指标驱动）
- 或有新的长文档（>2000 token）场景需求时（需求驱动）
- 独立 PR + 前后评测对照 + 引用校验重设计同步交付
