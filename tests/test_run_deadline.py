# -*- coding: utf-8 -*-
"""运行级端到端 deadline 单测（D6）。

背景：一轮运行只受 max_iters 和工具超时约束，无总时长上限。RUN_MAX_SECONDS
> 0 时 AG-UI 运行时挂 watchdog，到期取消并按 RUN_ERROR(code=DEADLINE_EXCEEDED)
收口；默认 0 = 不启用，行为不变。
"""
import asyncio
from types import SimpleNamespace

from ag_ui.core import RunAgentInput

from app.application.agents.orchestrator import SubmitIntentInput
from app.presentation.ag_ui_runtime import AGUIRuntime
from tests.test_runtime_lease import FlakyJournal, SlowOrchestrator, _body, _intent


class TestRunDeadline:
    async def test_deadline_cancels_run_with_specific_code(self):
        journal = FlakyJournal(failures=0)
        orchestrator = SlowOrchestrator(duration=1.0)
        runtime = AGUIRuntime(journal, orchestrator, lease_seconds=5.0, heartbeat_seconds=0.5,
                              run_max_seconds=0.1)
        appended = []
        original_append = journal.append

        async def spy_append(run_id, owner, events):
            appended.extend(events)
            return await original_append(run_id, owner, events)

        journal.append = spy_append
        await runtime.start(_body(), _intent())
        for _ in range(100):
            if orchestrator.cancelled:
                break
            await asyncio.sleep(0.05)
        assert orchestrator.cancelled, "超过 RUN_MAX_SECONDS 的运行必须被取消"
        errors = [event for event in appended if event["type"] == "RUN_ERROR"]
        assert errors and errors[-1].get("code") == "DEADLINE_EXCEEDED"
        assert "r-lease" not in runtime.running

    async def test_zero_disables_deadline(self):
        journal = FlakyJournal(failures=0)
        orchestrator = SlowOrchestrator(duration=0.2)
        runtime = AGUIRuntime(journal, orchestrator, lease_seconds=5.0, heartbeat_seconds=0.5,
                              run_max_seconds=0)
        await runtime.start(_body(), _intent())
        for _ in range(100):
            if orchestrator.finished:
                break
            await asyncio.sleep(0.05)
        assert orchestrator.finished, "RUN_MAX_SECONDS=0 表示不启用 deadline"
