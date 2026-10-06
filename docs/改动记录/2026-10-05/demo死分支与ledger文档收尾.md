# make demo 死分支与 ledger 退役文档收尾（P0）

## 需求

ADR-0008 退役 growth 事件消费线时，`scripts/runtime.py:152` 仍无条件生成 `SMARTLECT_GROWTH_EVENTS_ENABLED=true`，`scripts/demo.py` 据此调用已删除的 `/internal/ledger/summary` 对账并断言——`make demo` 走到该分支必然 404 重试至超时失败。同批过时文档（`assistant/LEDGER.md`、`assistant/README.md`、`docs/prod-hardening/recon-deadletter.md`）仍把退役 worker/ledger 线描述为现役。

## 具体变更

- `scripts/demo.py`：删除 143-155 ledger 对账分支、`"full_growth_loop"` 结果键（全仓无读取方）、`urllib.request` dead import（`json` 保留，`--output` 序列化仍用）；删除处留 ADR-0008 溯源注释。
- `scripts/runtime.py`：bootstrap 新建 env 不再写 `SMARTLECT_GROWTH_EVENTS_ENABLED`。
- `assistant/LEDGER.md`：头部加「已退役（ADR-0008）」标注块，指明 worker/端点/开关均已删、保留清理已并入 API 进程；正文作为 F1/P2 历史记录保留（不改写历史证据）。
- `assistant/README.md`：删除「Event consumption is disabled unless…」句，替换为退役说明。
- `docs/prod-hardening/recon-deadletter.md`：对账口径表 growth 侧行标注已退役、账务事实以 Java 权威侧为准。
- `assistant/tests/test_foundations.py` 的 `/internal/ledger/summary` 反向 404 断言**保留**（退役守卫）。

## 验证

- `python3 -m py_compile scripts/demo.py scripts/runtime.py` 通过。
- 全仓 grep：`SMARTLECT_GROWTH_EVENTS_ENABLED` 仅剩 LEDGER.md（历史标注内）；`/internal/ledger` 仅剩 demo 注释、test_foundations 反向断言、两处已标注文档。
- `make demo` 全链路未跑（需 12 进程全栈环境）；脚本级验证为语法 + 引用收敛。

## 未完成项

- 无（`make demo` 的全栈回归属发布验收，不在本批范围）。

## 关联代码版本

基于 `7773906` 工作树（本批未单独提交）。
