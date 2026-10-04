# -*- coding: utf-8 -*-
"""DashScope 流式语音识别 client（对话入口语音转文字专用）。

职责边界：音频进、转写事件出。识别文本由前端回填输入框后走既有
AG-UI 文本链路，本模块不触碰对话编排，音频不落库不写日志。

SDK 的 Recognition 回调跑在其内部 WS 线程，经 call_soon_threadsafe
桥接回事件循环；start/stop 均为阻塞调用，一律放线程池执行。

2026-10-03 实测（qwen-audio-3.1-asr-flash-message）事件要点：
- sentence 帧带显式 sentence_end 布尔；流收尾帧 end_time=-1 不是真实句尾，
  因此 final 判定以 sentence_end 为主、end_time>=0 兜底（兼容 paraformer 老协议）；
- 空文本 partial/final 直接丢弃，不下发给前端。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from app.infrastructure.settings import Settings

logger = logging.getLogger(__name__)


class VoiceAsrError(Exception):
    """识别链路错误；code 会经 WS 下发给前端做降级提示。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AsrEvent:
    type: str  # partial / final / error / complete
    text: str = ""
    code: str = ""


def _classify_error(status_code, code: str) -> str:
    if code == "ModelNotFound":
        return "model_not_found"
    if status_code in (401, 403):
        return "auth"
    if code in ("TaskTimeout", "SilenceTimeout", "IdleTimeout"):
        return "timeout"
    return "upstream"


def _sentence_text(sentence: dict) -> tuple[str, bool]:
    """返回 (文本, 是否句尾终稿)；空文本返回 ("", False) 表示跳过。"""
    text = (sentence.get("text") or "").strip()
    if not text:
        return "", False
    is_final = bool(sentence.get("sentence_end")) or (
        sentence.get("end_time") is not None and sentence.get("end_time") >= 0
    )
    return text, is_final


class RecognitionSession:
    """一条语音连接对应的识别会话；SDK 回调线程经队列送出事件，None 表示流终止。"""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.queue: asyncio.Queue[AsrEvent | None] = asyncio.Queue()
        self._loop = loop
        self._recognition = None

    def bind(self, recognition) -> None:
        self._recognition = recognition

    # ---- SDK 回调（工作线程），禁止直接触碰 asyncio 对象 ----
    def _emit(self, event: AsrEvent | None) -> None:
        self._loop.call_soon_threadsafe(self.queue.put_nowait, event)

    def on_open(self) -> None:  # pragma: no cover - SDK 触达点
        pass

    def on_event(self, result) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        text, is_final = _sentence_text(sentence)
        if not text:
            return
        self._emit(AsrEvent("final" if is_final else "partial", text=text))

    def on_error(self, result) -> None:
        code = _classify_error(getattr(result, "status_code", None), str(getattr(result, "code", "") or ""))
        message = str(getattr(result, "message", "") or "识别服务返回错误")
        logger.warning("语音识别上游错误 code=%s message=%s", code, message)
        self._emit(AsrEvent("error", text=message, code=code))
        self._emit(None)

    def on_complete(self) -> None:
        self._emit(AsrEvent("complete"))
        self._emit(None)

    def on_close(self) -> None:
        self._emit(None)

    # ---- 异步侧接口 ----
    async def feed(self, frame: bytes) -> None:
        if self._recognition is not None:
            await asyncio.to_thread(self._recognition.send_audio_frame, frame)

    async def finish(self) -> None:
        """正常收口：送 task-finish 并等待剩余事件（阻塞调用放线程池）。"""
        if self._recognition is None:
            return
        recognition, self._recognition = self._recognition, None
        await asyncio.to_thread(recognition.stop)

    async def abort(self) -> None:
        """客户端断开时的尽力释放；stop 卡死则放弃引用交给 SDK 析构兜底。"""
        if self._recognition is None:
            return
        recognition, self._recognition = self._recognition, None
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.to_thread(recognition.stop), timeout=3.0)


class DashScopeVoiceAsr:
    """进程级服务对象；每条语音连接经 start() 建独立识别会话。"""

    def __init__(self, settings: Settings, context_prompt: str = "") -> None:
        self._settings = settings
        self._context_prompt = context_prompt

    @property
    def model(self) -> str:
        return self._settings.voice_asr_model

    async def start(self) -> RecognitionSession:
        import dashscope
        from dashscope.audio.asr import Recognition

        if self._settings.dashscope_api_key:
            dashscope.api_key = self._settings.dashscope_api_key
        kwargs: dict = {}
        # 上下文 Prompt 是 qwen 系识别参数（3.1 message 实测接受）；
        # fun-asr / paraformer 不认该参数，传入可能 InvalidParameter，按模型名区分。
        if self._context_prompt and "qwen" in self._settings.voice_asr_model.lower():
            kwargs["context"] = self._context_prompt
        session = RecognitionSession(asyncio.get_running_loop())
        recognition = Recognition(
            model=self._settings.voice_asr_model,
            callback=session,
            format="pcm",
            sample_rate=16000,
            **kwargs,
        )
        session.bind(recognition)
        try:
            await asyncio.to_thread(recognition.start)
        except Exception as err:  # noqa: BLE001
            raise VoiceAsrError("start_failed", f"识别会话建立失败：{err}") from err
        return session
