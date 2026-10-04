# -*- coding: utf-8 -*-
"""运行独立于 HTTP 订阅存在；日志写入成功后事件才对 SSE 可见。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
import uuid

from ag_ui.core import RunAgentInput

from app.application.agents.ag_ui_adapter import AGUIRunAdapter
from app.application.agents.orchestrator import SubmitIntentInput
from app.infrastructure.ag_ui_journal import AGUIJournal, JournalLeaseLost
from app.infrastructure.eventbus import observe_run_events

logger = logging.getLogger(__name__)


@dataclass
class Running:
    owner: str
    deadline: float
    valid: bool = True
    reason: str = ""
    task: asyncio.Task | None = None

    def is_valid(self):
        return self.valid and time.monotonic() < self.deadline


class AGUIRuntime:
    def __init__(self, journal: AGUIJournal, orchestrator, confirmations=None, *,
                 lease_seconds=30, heartbeat_seconds=5,
                 retention_days: int = 0, run_max_seconds: int = 0):
        self.journal, self.orchestrator, self.confirmations = journal, orchestrator, confirmations
        self.lease_seconds, self.heartbeat_seconds = lease_seconds, heartbeat_seconds
        # D3：事件保留天数（0=关闭）；D6：单次运行端到端时长上限秒数（0=不启用）
        self.retention_days = retention_days
        self.run_max_seconds = run_max_seconds
        self.running: dict[str, Running] = {}
        self._retention_task: asyncio.Task | None = None

    async def startup(self):
        await self.journal.initialize()
        await self.journal.recover_expired()
        if self.retention_days > 0:
            self._retention_task = asyncio.create_task(self._retention_loop())

    async def _retention_loop(self):
        """每小时执行一次事件归档；单轮失败只告警，不影响运行时。"""
        while True:
            try:
                report = await self.journal.archive_stale_events(self.retention_days)
                if report["archived_runs"]:
                    logger.info("AG-UI 事件归档完成：%s", report)
            except Exception as err:  # noqa: BLE001 —— 维护任务不能影响主链路
                logger.warning("AG-UI 事件归档执行失败（下轮重试）：%s", err)
            await asyncio.sleep(3600)

    async def shutdown(self):
        if self._retention_task is not None:
            self._retention_task.cancel()
            await asyncio.gather(self._retention_task, return_exceptions=True)
            self._retention_task = None
        active = list(self.running.items())
        for _, entry in active:
            entry.reason = "restart"
            entry.valid = False
            if entry.task:
                entry.task.cancel()
        await asyncio.gather(*(entry.task for _, entry in active if entry.task), return_exceptions=True)
        for run_id, entry in active:
            await self.journal.end_owned(run_id, entry.owner)
            self.running.pop(run_id, None)

    async def start(self, body: RunAgentInput, intent: SubmitIntentInput):
        owner = uuid.uuid4().hex
        run, created = await self.journal.reserve(body.model_dump(mode="json", by_alias=True), intent.buyer_id, owner, self.lease_seconds)
        if created:
            # deadline 必须在 reserve 返回后重算：reserve 可能因 SQLite 锁等待耗时，
            # 用调用前的时间戳会让 entry 出生即临近过期，首次心跳直接误判失效。
            entry = Running(owner, time.monotonic() + self.lease_seconds)
            self.running[body.run_id] = entry
            effective = RunAgentInput.model_validate(run["input"])
            entry.task = asyncio.create_task(self._produce(effective, intent, entry), name=f"agui-run:{body.run_id}")
        return run

    async def cancel(self, run_id, buyer_id):
        run = await self.journal.request_stop(run_id, buyer_id)
        entry = self.running.get(run_id)
        if entry and entry.task:
            entry.reason = "stop"
            entry.valid = False
            entry.task.cancel()
            await asyncio.shield(asyncio.gather(entry.task, return_exceptions=True))
            await self.journal.end_owned(run_id, entry.owner, stopped=True)
            self.running.pop(run_id, None)
            run = await self.journal.run(run_id, buyer_id)
        return run

    async def _produce(self, body, intent, entry):
        queue = asyncio.Queue()
        adapter = AGUIRunAdapter(body, queue.put_nowait, authoritative_state=body.state)

        async def write_events():
            backlog_warned = False
            while True:
                event = await queue.get()
                if event is None:
                    return
                if not backlog_warned and queue.qsize() >= 2048:
                    # journal 是回放权威，事件不能丢；只能告警暴露写入跟不上生成。
                    backlog_warned = True
                    logger.warning("AG-UI 事件写入积压达高水位（%d），检查 journal 写入延迟：%s", queue.qsize(), body.run_id)
                events = [event]
                ending = False
                while len(events) < 64 and not queue.empty():
                    following = queue.get_nowait()
                    if following is None:
                        ending = True
                        break
                    events.append(following)
                payloads = [value.model_dump(mode="json", by_alias=True, exclude_none=True) for value in events]
                if entry.reason == "restart":
                    for value in payloads:
                        if value["type"] == "RUN_ERROR":
                            value["code"] = "SERVER_RESTART"
                try:
                    await self.journal.append(body.run_id, entry.owner, payloads)
                except Exception:
                    entry.valid = False
                    entry.reason = "restart"
                    if entry.task:
                        entry.task.cancel()
                    raise
                if ending:
                    return

        async def heartbeat():
            while True:
                await asyncio.sleep(self.heartbeat_seconds)
                started = time.monotonic()
                try:
                    renewed = None
                    # 瞬时存储错误（SQLite busy 等）在租约剩余时间内有界重试；
                    # renew == False 是权威的易主/停止判定，不重试。
                    for _attempt in range(3):
                        try:
                            renewed = await asyncio.wait_for(
                                self.journal.renew(body.run_id, entry.owner, self.lease_seconds),
                                max(0.001, entry.deadline - time.monotonic()),
                            )
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception as renew_error:
                            logger.warning("运行日志续租异常，将在租约期内重试（%s）：%s", body.run_id, renew_error)
                            if entry.deadline - time.monotonic() <= max(1.0, self.lease_seconds / 10):
                                break
                            await asyncio.sleep(0.5)
                    if renewed is not True:
                        if renewed is False:
                            run = await self.journal.run(body.run_id, intent.buyer_id)
                            entry.reason = "stop" if run["stopRequested"] else "restart"
                            raise JournalLeaseLost("运行日志租约失效或收到跨实例停止请求")
                        raise JournalLeaseLost("运行日志租约未能在剩余时间内完成续期，按失效处理")
                    entry.deadline = started + self.lease_seconds
                except Exception:
                    entry.valid = False
                    if entry.task:
                        entry.task.cancel()
                    return

        writer = asyncio.create_task(write_events())
        lease_task = asyncio.create_task(heartbeat())
        deadline_task = None
        if self.run_max_seconds > 0:
            # D6：端到端时长上限。到期取消运行并按 DEADLINE_EXCEEDED 收口；
            # 租约只防重复执行、不限时长，此前一轮只受 max_iters 与工具超时约束。
            async def deadline_watchdog():
                await asyncio.sleep(self.run_max_seconds)
                if entry.valid:
                    entry.reason = "deadline"
                    entry.task.cancel()
            deadline_task = asyncio.create_task(deadline_watchdog())
        adapter.start()
        try:
            if self.confirmations is not None:
                saved = await self.confirmations.list(intent.buyer_id, intent.shopping_session_id)
                adapter.state["confirmations"] = saved["confirmations"]
                adapter.snapshot()
            with observe_run_events(adapter.on_trade_event):
                result = await self.orchestrator.handle_intent(intent, event_observer=adapter.on_agent_event,
                    use_semantic_cache=True, persistence_guard=entry.is_valid)
            if not entry.is_valid():
                raise asyncio.CancelledError()
            if getattr(result,"error_code",None)=="SESSION_VERSION_CHANGED":
                adapter.state["resumeDestination"]=await self.journal.latest_destination(intent.shopping_session_id,intent.buyer_id)
            if result.error or adapter.error:
                adapter.fail(result.error if getattr(result,"error_code",None) in {"SESSION_VERSION_CHANGED","CONTEXT_CAPACITY_EXCEEDED"} else adapter.error or "本轮服务暂时未能完成请求，请重试。", code=getattr(result,"error_code",None))
            else:
                adapter.finish(result.final_text)
        except asyncio.CancelledError:
            if entry.reason == "deadline":
                adapter.fail("本轮超过最大运行时长限制已中断，已保存的内容仍可恢复。", code="DEADLINE_EXCEEDED")
            else:
                adapter.fail("本轮已明确停止" if entry.reason == "stop" else "服务重启或执行中断，已保存的内容仍可恢复。", cancelled=entry.reason == "stop")
        except Exception:
            logger.exception("AG-UI 运行失败：%s", body.run_id)
            adapter.fail("本轮服务暂时未能完成请求，请重试。")
        finally:
            if deadline_task is not None:
                deadline_task.cancel()
                await asyncio.gather(deadline_task, return_exceptions=True)
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
            queue.put_nowait(None)
            try:
                await writer
            except Exception:
                logger.exception("AG-UI 日志写入失败，等待持久租约过期后标记中断：%s", body.run_id)
            entry.valid = False
            self.running.pop(body.run_id, None)
