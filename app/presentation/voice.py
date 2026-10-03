# -*- coding: utf-8 -*-
"""语音输入入口：能力探测 + 流式识别 WebSocket。

音频只在识别链路内流转，不落库不写日志；转写文本由前端回填输入框后
走既有 AG-UI 文本链路，本模块不触碰对话编排。

上行协议：二进制帧 = 16kHz/16bit/单声道 PCM；文本帧 {"type":"finish"} 主动结束。
下行协议：{"type":"partial"|"final","text":...}、{"type":"error","code","message"}、
{"type":"stopped","reason":"finished"|"timeout"|"idle"}。

生命周期约束：每条连接恰好一个识别会话，断开即释放；
全局并发受 VOICE_ASR_MAX_SESSIONS 限制，满载快速失败不排队。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

import anyio
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.infrastructure.voice.dashscope_asr import AsrEvent, DashScopeVoiceAsr, VoiceAsrError
from app.presentation.identity import require_buyer

logger = logging.getLogger(__name__)

_CLOSE_CODES = {401: 4401, 403: 4403, 422: 4400}


def register_voice_routes(api: FastAPI, get_voice_asr, get_settings) -> None:
    # 并发闸门依赖 settings（lifespan 才加载），首次连接时惰性创建。
    gate: dict[str, asyncio.Semaphore] = {}

    def _gate(settings) -> asyncio.Semaphore:
        if "s" not in gate:
            gate["s"] = asyncio.Semaphore(max(1, settings.voice_asr_max_sessions))
        return gate["s"]

    @api.get("/commerce/voice/capabilities")
    async def voice_capabilities(request: Request):
        # 只读能力探测（是否启用 + 模型名），不含敏感信息，无需鉴权。
        asr = get_voice_asr()
        return {"enabled": asr is not None, "model": asr.model if asr is not None else ""}

    @api.websocket("/commerce/voice/asr")
    async def voice_asr_socket(websocket: WebSocket) -> None:
        asr = get_voice_asr()
        if asr is None:
            await websocket.close(code=4404, reason="语音识别未启用")
            return
        settings = get_settings()
        protocols = websocket.scope.get("subprotocols", [])
        # 只回显公开协议名，认证令牌不进入响应头或 URL。
        await websocket.accept(subprotocol="smartlect-voice" if "smartlect-voice" in protocols else None)
        try:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                raise HTTPException(status_code=422, detail="识别连接需要买家身份")
            await require_buyer(websocket, payload.get("buyer_id"))
        except WebSocketDisconnect:
            return
        except (HTTPException, ValueError) as error:
            status = error.status_code if isinstance(error, HTTPException) else 422
            await websocket.close(code=_CLOSE_CODES.get(status, 4400), reason="语音识别身份校验失败")
            return

        semaphore = _gate(settings)
        if semaphore.locked():
            await websocket.send_json({"type": "error", "code": "busy", "message": "识别并发已满，请稍后再试"})
            await websocket.close(code=4429, reason="识别并发已满")
            return
        async with semaphore:
            await _serve_session(websocket, asr, settings)


async def _serve_session(websocket: WebSocket, asr: DashScopeVoiceAsr, settings) -> None:
    try:
        session = await asr.start()
    except VoiceAsrError as error:
        logger.warning("语音识别会话建立失败 code=%s", error.code)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "code": error.code, "message": str(error)})
            await websocket.close(code=1011)
        return

    async def pump_up() -> str:
        """收上行：二进制 PCM 喂识别；finish 文本帧结束；receive 空闲超时抛 TimeoutError。"""
        while True:
            message = await asyncio.wait_for(websocket.receive(), timeout=settings.voice_asr_idle_seconds)
            if message["type"] == "websocket.disconnect":
                return "disconnected"
            frame = message.get("bytes")
            if frame:
                await session.feed(frame)
                continue
            text = message.get("text")
            if text:
                with contextlib.suppress(ValueError):
                    payload = json.loads(text)
                    if isinstance(payload, dict) and payload.get("type") == "finish":
                        return "finished"

    async def pump_down():
        """下发识别事件；收到 sentinel 返回 None，错误事件冒泡返回 AsrEvent。"""
        while True:
            event = await session.queue.get()
            if event is None:
                return None
            if event.type == "error":
                return event
            if event.type in ("partial", "final"):
                await websocket.send_json({"type": event.type, "text": event.text})

    up_task = asyncio.create_task(pump_up())
    down_task = asyncio.create_task(pump_down())
    reason = "finished"
    disconnected = False
    upstream_error: AsrEvent | None = None

    with anyio.move_on_after(settings.voice_asr_max_seconds) as scope:
        await asyncio.wait({up_task, down_task}, return_when=asyncio.FIRST_COMPLETED)
    timed_out = scope.cancelled_caught

    # move_on_after 不取消内部任务，统一取消后取结果（结果顺序与参数顺序一致）
    for task in (up_task, down_task):
        task.cancel()
    up_result, down_result = await asyncio.gather(up_task, down_task, return_exceptions=True)

    if isinstance(up_result, asyncio.TimeoutError):
        reason = "idle"
    elif isinstance(up_result, WebSocketDisconnect) or up_result == "disconnected":
        disconnected = True
    if not isinstance(down_result, BaseException) and isinstance(down_result, AsrEvent):
        upstream_error = down_result
    if timed_out:
        reason = "timeout"

    if disconnected:
        await session.abort()
        return

    if upstream_error is None:
        # 正常收口：送 task-finish 并等待 SDK 回调补发剩余事件（5 秒上限）
        with contextlib.suppress(Exception):
            await session.finish()
        upstream_error = await _drain_tail(websocket, session)
    else:
        # 上游已报错终止，drain 只为清理，不再期待新事件
        await _drain_tail(websocket, session)

    if upstream_error is not None:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "code": upstream_error.code, "message": upstream_error.text})
        await session.abort()
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
        return
    with contextlib.suppress(Exception):
        await websocket.send_json({"type": "stopped", "reason": reason})
        await websocket.close(code=1000)


async def _drain_tail(websocket: WebSocket, session, timeout: float = 5.0):
    """finish() 之后把队列中剩余事件发完；返回错误事件（如有）。

    call_soon_threadsafe 的回调在事件循环下个周期才入队，stop() 返回后
    事件未必立刻可读，因此用带超时的 await 而不是 get_nowait。
    """
    deadline = asyncio.get_event_loop().time() + timeout
    error: AsrEvent | None = None
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return error
        try:
            event = await asyncio.wait_for(session.queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            return error
        if event is None:
            return error
        if event.type == "error":
            error = event
        elif event.type in ("partial", "final"):
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": event.type, "text": event.text})
