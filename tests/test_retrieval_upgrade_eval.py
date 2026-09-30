"""整套固定目录评测必须能覆盖空结果样本，不能因缺少 filter_ok 中断。"""

import json
from unittest.mock import AsyncMock


async def test_offline_report_records_negative_cases_and_blocked_dependency(
    monkeypatch, tmp_path
):
    from scripts.eval import retrieval_upgrade

    monkeypatch.setattr(
        retrieval_upgrade.OpenAIEmbeddingClient,
        "embed",
        AsyncMock(side_effect=RuntimeError("测试中禁用外部服务")),
    )
    await retrieval_upgrade.evaluate(tmp_path / "report")
    result = json.loads((tmp_path / "report/report.json").read_text())
    assert result["hybrid_quality"] == "BLOCKED_EMBEDDING"
    assert result["promotion"] == "NOT_APPROVED"
    # v1 正式集已扩充至 750（150 冻结 + 600 扩充，见 expand_eval_v1.py）
    assert result["experiments"][0]["scenarios"] == 750
    for value in result["experiments"][0]["summary"].values():
        assert value["actual_model_calls"] == 0
        assert value["hard_constraint_failures"] == 0
