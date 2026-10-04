# -*- coding: utf-8 -*-
"""Journal 读路径免写锁单测（B6）。

背景：run/events/session/sessions 原先全部在 BEGIN IMMEDIATE 写事务里跑
_recover，SSE 重连/事件轮询等热路径每次都抢 SQLite 写锁。现在改为只读探测，
确认存在过期运行才升级写事务。
"""
import asyncio

from app.infrastructure.ag_ui_journal import AGUIJournal
from tests.test_ag_ui_journal import body


def _spy_recover(monkeypatch, counter):
    original = AGUIJournal._recover

    def spy(*args, **kwargs):
        counter["calls"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(AGUIJournal, "_recover", spy)


async def test_read_paths_skip_recovery_when_nothing_expired(tmp_path, monkeypatch):
    journal = AGUIJournal(tmp_path / "runs.db")
    await journal.initialize()
    await journal.reserve(body(), "b1", "owner", lease_seconds=60)
    await journal.append("r1", "owner", [
        {"type": "RUN_STARTED", "threadId": "s1", "runId": "r1"},
        {"type": "RUN_FINISHED", "threadId": "s1", "runId": "r1"},
    ])

    counter = {"calls": 0}
    _spy_recover(monkeypatch, counter)
    await journal.run("r1", "b1")
    await journal.events("r1", "b1")
    await journal.sessions("b1")
    await journal.session("s1", "b1")
    assert counter["calls"] == 0, "无过期运行时读路径不应执行恢复（不应升级写事务）"


async def test_recovery_still_runs_when_run_expired(tmp_path, monkeypatch):
    journal = AGUIJournal(tmp_path / "runs.db")
    await journal.initialize()
    await journal.reserve(body(), "b1", "owner", lease_seconds=0.05)
    await asyncio.sleep(0.3)

    counter = {"calls": 0}
    _spy_recover(monkeypatch, counter)
    run = await journal.run("r1", "b1")
    assert run["status"] == "interrupted", "过期运行仍须被恢复为中断终态"
    assert counter["calls"] >= 1, "存在过期运行时必须执行恢复"


async def test_read_results_unchanged_after_refactor(tmp_path):
    journal = AGUIJournal(tmp_path / "runs.db")
    await journal.initialize()
    await journal.reserve(body(), "b1", "owner", lease_seconds=60)
    await journal.append("r1", "owner", [
        {"type": "RUN_STARTED", "threadId": "s1", "runId": "r1"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "回复正文"},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "RUN_FINISHED", "threadId": "s1", "runId": "r1"},
    ])
    events, status, cursor = await journal.events("r1", "b1")
    assert status == "completed" and cursor == 5
    session = await journal.session("s1", "b1")
    assert session["messages"][-1]["content"] == "回复正文"
