# -*- coding: utf-8 -*-
"""运行时/队列租约心跳容错单测（B7）。

背景：心跳对一次 renew 异常（SQLite busy / Redis 抖动）零容忍会误杀在途运行；
renew == False 才是权威的易主判定。异常应在租约剩余时间内有界重试。
"""
import asyncio
import time
from types import SimpleNamespace

import pytest
from ag_ui.core import RunAgentInput

from app.application.agents.orchestrator import SubmitIntentInput
from app.infrastructure.queue.redis_stream_queue import ExecutionLease, RedisStreamTaskQueue
from app.presentation.ag_ui_runtime import AGUIRuntime


def _body():
    return RunAgentInput.model_validate({
        "threadId": "s-lease", "runId": "r-lease", "state": {},
        "messages": [{"id": "u1", "role": "user", "content": "查一下"}],
        "tools": [], "context": [], "forwardedProps": {},
    })


def _intent():
    return SubmitIntentInput(
        shopping_session_id="s-lease", buyer_id="b-lease",
        locale="zh-CN", currency="CNY", raw_query="查一下",
    )


class FlakyJournal:
    """renew 前 failures 次抛存储异常，之后成功；其余方法最小打桩。"""

    def __init__(self, failures: int = 1, renew_result: bool = True):
        self.failures = failures
        self.renew_result = renew_result
        self.renew_calls = 0

    async def initialize(self):
        return None

    async def recover_expired(self):
        return None

    async def reserve(self, body, buyer_id, owner, lease_seconds=30):
        return {
            "runId": "r-lease", "threadId": "s-lease", "status": "running", "cursor": 0,
            "stopRequested": False, "input": body, "messages": [], "state": {}, "updatedAt": 0,
        }, True

    async def renew(self, run_id, owner, lease_seconds):
        self.renew_calls += 1
        if self.renew_calls <= self.failures:
            raise RuntimeError("database is locked")
        return self.renew_result

    async def append(self, run_id, owner, events):
        return None

    async def run(self, run_id, buyer_id):
        return {"stopRequested": False}

    async def end_owned(self, run_id, owner, stopped=False):
        return None

    async def latest_destination(self, session_id, buyer_id):
        return None


class SlowOrchestrator:
    def __init__(self, duration: float = 0.3):
        self.duration = duration
        self.finished = False
        self.cancelled = False

    async def handle_intent(self, intent, **kwargs):
        try:
            await asyncio.sleep(self.duration)
            self.finished = True
            return SimpleNamespace(error=None, final_text="ok")
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class TestAGUIRuntimeHeartbeat:
    async def test_transient_journal_error_retried_and_run_completes(self):
        # 运行时长（1.0s）须大于重试延迟（0.5s），否则运行先结束、心跳被正常
        # 取消，重试不会发生——那是另一种正确的系统行为，不是本用例要验证的。
        journal = FlakyJournal(failures=1)
        orchestrator = SlowOrchestrator(duration=1.0)
        runtime = AGUIRuntime(journal, orchestrator, lease_seconds=2.0, heartbeat_seconds=0.05)
        await runtime.start(_body(), _intent())
        for _ in range(100):
            if orchestrator.finished and journal.renew_calls >= 2:
                break
            await asyncio.sleep(0.05)
        assert orchestrator.finished, "一次 SQLite busy 不应取消在途运行"
        assert journal.renew_calls >= 2, "异常后必须重试续租"
        assert "r-lease" not in runtime.running

    async def test_authoritative_lease_loss_cancels_run(self):
        # failures=0：首次续租即返回 False（权威易主），必须在运行完成前（0.3s）
        # 就取消；若首测是异常重试路径，丢失判定会推迟到重试之后。
        journal = FlakyJournal(failures=0, renew_result=False)
        orchestrator = SlowOrchestrator()
        runtime = AGUIRuntime(journal, orchestrator, lease_seconds=2.0, heartbeat_seconds=0.05)
        await runtime.start(_body(), _intent())
        for _ in range(100):
            if orchestrator.cancelled:
                break
            await asyncio.sleep(0.05)
        assert orchestrator.cancelled, "确认易主（renew=False）必须取消运行"
        assert "r-lease" not in runtime.running

    async def test_fresh_deadline_after_reserve(self):
        """entry.deadline 必须在 reserve 返回后重算，不能包含 reserve 的等待时间。"""
        journal = FlakyJournal()
        runtime = AGUIRuntime(journal, SlowOrchestrator(), lease_seconds=2.0)
        await runtime.start(_body(), _intent())
        entry = runtime.running["r-lease"]
        remaining = entry.deadline - time.monotonic()
        assert 1.5 < remaining <= 2.0, "剩余租期应接近完整 lease_seconds"


class FlakyEvalClient:
    """按脚本返回 eval 结果；Exception 实例表示抛出。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def eval(self, *args, **kwargs):
        self.calls += 1
        result = self.script.pop(0) if self.script else 1
        if isinstance(result, Exception):
            raise result
        return result


class TestQueueHeartbeat:
    def _lease(self, seconds: float = 2.0) -> ExecutionLease:
        lease = ExecutionLease(session_id="s", owner="o", lease_ms=int(seconds * 1000))
        lease.ready = True
        lease.expires_at = time.monotonic() + seconds
        return lease

    async def test_transient_eval_error_retried(self):
        queue = RedisStreamTaskQueue(FlakyEvalClient([RuntimeError("redis blip"), 1]))
        lease = self._lease()
        owner_task = asyncio.create_task(asyncio.sleep(10))
        try:
            heartbeat = asyncio.create_task(queue._heartbeat(lease, owner_task, 50))
            await asyncio.sleep(0.3)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            assert lease.valid, "一次 Redis 抖动不应判死执行租约"
            assert not owner_task.cancelled()
        finally:
            owner_task.cancel()

    async def test_owner_loss_cancels_owner_task(self):
        queue = RedisStreamTaskQueue(FlakyEvalClient([0]))
        lease = self._lease()
        owner_task = asyncio.create_task(asyncio.sleep(10))
        heartbeat = asyncio.create_task(queue._heartbeat(lease, owner_task, 50))
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(owner_task), 2)
            assert lease.valid is False
        finally:
            heartbeat.cancel()
            owner_task.cancel()
            await asyncio.gather(heartbeat, owner_task, return_exceptions=True)
