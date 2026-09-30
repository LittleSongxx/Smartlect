# -*- coding: utf-8 -*-
"""AG-UI 事件日志保留策略单测（D3）。

背景：agui_events 无保留策略，事件随会话无限增长。策略：空闲超过 N 天的
会话中**非 last_run** 的 runs 事件移入归档库后删除；runs 投影与 session 行
保留（history restore 读投影不读事件，不受影响）。0 = 关闭。
"""
import asyncio
import sqlite3

from app.infrastructure.ag_ui_journal import AGUIJournal
from tests.test_ag_ui_journal import body


def _backdate(path, session_id, days=30):
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE agui_sessions SET updated_at = updated_at - ? WHERE session_id=?",
            (days * 86400, session_id),
        )
        connection.commit()
    finally:
        connection.close()


async def _complete_run(journal, run_id, text, message_id="m1"):
    await journal.append(run_id, "owner", [
        {"type": "RUN_STARTED", "threadId": "s1", "runId": run_id},
        {"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": text},
        {"type": "TEXT_MESSAGE_END", "messageId": message_id},
        {"type": "RUN_FINISHED", "threadId": "s1", "runId": run_id},
    ])


async def test_retention_archives_non_last_run_events_and_keeps_restore(tmp_path):
    path = tmp_path / "runs.db"
    journal = AGUIJournal(path)
    await journal.initialize()
    await journal.reserve(body(), "b1", "owner")
    await _complete_run(journal, "r1", "第一轮回复")
    second = body()
    second["runId"] = "r2"
    second["messages"] = [*body()["messages"], {"id": "u2", "role": "user", "content": "第二轮"}]
    await journal.reserve(second, "b1", "owner")
    await _complete_run(journal, "r2", "第二轮回复", message_id="m2")
    _backdate(path, "s1", days=30)

    report = await journal.archive_stale_events(retention_days=7)
    assert report["archived_runs"] == 1, "只归档非 last_run（r1）"
    assert report["archived_events"] == 5

    # 消息合并恢复不受影响（读投影不读事件）
    session = await AGUIJournal(path).session("s1", "b1")
    contents = [message["content"] for message in session["messages"]]
    assert "第一轮回复" in contents and "第二轮回复" in contents
    # last_run 的事件回放保留
    events, status, _ = await AGUIJournal(path).events("r2", "b1")
    assert status == "completed" and len(events) == 5
    # 已归档 run 的事件回放变空，但游标状态仍一致
    events, status, cursor = await AGUIJournal(path).events("r1", "b1")
    assert status == "completed" and events == [] and cursor == 5

    # 幂等：重复执行不再归档
    report = await AGUIJournal(path).archive_stale_events(retention_days=7)
    assert report["archived_runs"] == 0


async def test_retention_disabled_by_default_and_recent_sessions_kept(tmp_path):
    path = tmp_path / "runs.db"
    journal = AGUIJournal(path)
    await journal.initialize()
    await journal.reserve(body(), "b1", "owner")
    await _complete_run(journal, "r1", "回复")
    _backdate(path, "s1", days=30)

    assert await journal.archive_stale_events(retention_days=0) == {"archived_runs": 0, "archived_events": 0}
    events, _, _ = await AGUIJournal(path).events("r1", "b1")
    assert len(events) == 5, "retention_days=0 表示不归档"

    # 未到保留期的会话不动
    report = await journal.archive_stale_events(retention_days=90)
    assert report == {"archived_runs": 0, "archived_events": 0}


async def test_archived_events_land_in_archive_database(tmp_path):
    path = tmp_path / "runs.db"
    journal = AGUIJournal(path)
    await journal.initialize()
    await journal.reserve(body(), "b1", "owner")
    await _complete_run(journal, "r1", "第一轮")
    second = body()
    second["runId"] = "r2"
    second["messages"] = [*body()["messages"], {"id": "u2", "role": "user", "content": "第二轮"}]
    await journal.reserve(second, "b1", "owner")
    await _complete_run(journal, "r2", "第二轮")
    _backdate(path, "s1", days=30)
    await journal.archive_stale_events(retention_days=7)

    archive = sqlite3.connect(path.parent / "runs.db.archive")
    try:
        count = archive.execute("SELECT COUNT(*) FROM agui_events WHERE run_id='r1'").fetchone()[0]
    finally:
        archive.close()
    assert count == 5, "被删除的事件必须完整落入归档库"
