# -*- coding: utf-8 -*-
"""语音输入路由测试：能力探测、WS 鉴权、流式识别主链路。

用假 ASR 会话驱动，不打真实 DashScope（外部链路验收见改动记录单列）。
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.infrastructure.identity import IdentityPolicy
from app.infrastructure.voice.catalog_context import build_asr_context
from app.infrastructure.voice.dashscope_asr import AsrEvent
from app.presentation.voice import register_voice_routes

POLICY = IdentityPolicy(mode="hmac", secret="local-test-secret-never-used-in-production-123456")


class FakeSession:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.fed: list[bytes] = []
        self.aborted = False

    async def feed(self, frame: bytes) -> None:
        self.fed.append(frame)
        # 喂什么吐什么，模拟 partial 回显
        self.queue.put_nowait(AsrEvent("partial", frame.decode("utf-8")))

    async def finish(self) -> None:
        self.queue.put_nowait(AsrEvent("final", "降噪耳机"))
        self.queue.put_nowait(None)

    async def abort(self) -> None:
        self.aborted = True
        self.queue.put_nowait(None)


class FakeAsr:
    model = "fake-asr-model"

    def __init__(self) -> None:
        self.session: FakeSession | None = None

    async def start(self) -> FakeSession:
        self.session = FakeSession()
        return self.session


def voice_settings(**overrides) -> SimpleNamespace:
    base = {"voice_asr_max_seconds": 60, "voice_asr_idle_seconds": 20, "voice_asr_max_sessions": 8}
    base.update(overrides)
    return SimpleNamespace(**base)


def build_api(asr=None, settings=None, identity=None) -> FastAPI:
    api = FastAPI()
    api.state.identity_policy = identity
    register_voice_routes(api, lambda: asr, lambda: settings or voice_settings())
    return api


def test_capabilities_report_disabled_without_asr():
    with TestClient(build_api(asr=None)) as client:
        body = client.get("/commerce/voice/capabilities").json()
        assert body == {"enabled": False, "model": ""}


def test_capabilities_report_enabled_with_model_name():
    asr = FakeAsr()
    with TestClient(build_api(asr=asr)) as client:
        body = client.get("/commerce/voice/capabilities").json()
        assert body == {"enabled": True, "model": "fake-asr-model"}


def test_disabled_asr_rejects_websocket_with_4404():
    with TestClient(build_api(asr=None)) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/commerce/voice/asr") as ws:
                ws.receive_json()
        assert error.value.code == 4404


def test_websocket_requires_valid_identity_in_hmac_mode():
    api = build_api(asr=FakeAsr(), identity=POLICY)
    with TestClient(api) as client:
        # 无凭证 / 坏凭证 / 凭证与声明买家不一致，均不得进入识别
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/commerce/voice/asr") as ws:
                ws.send_json({"buyer_id": "buyer-1"})
                ws.receive_json()
        assert error.value.code == 4401
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/commerce/voice/asr",
                subprotocols=["smartlect-voice", "smartlect-auth." + POLICY.issue("buyer-1")]) as ws:
                ws.send_json({"buyer_id": "buyer-2"})
                ws.receive_json()
        assert error.value.code == 4403


def test_stream_flow_feeds_audio_and_finishes_with_final_text():
    asr = FakeAsr()
    with TestClient(build_api(asr=asr)) as client:
        with client.websocket_connect("/commerce/voice/asr", subprotocols=["smartlect-voice"]) as ws:
            assert ws.accepted_subprotocol == "smartlect-voice"
            ws.send_json({"buyer_id": "smartlect"})
            ws.send_bytes("我想买一副".encode("utf-8"))
            assert ws.receive_json() == {"type": "partial", "text": "我想买一副"}
            ws.send_json({"type": "finish"})
            assert ws.receive_json() == {"type": "final", "text": "降噪耳机"}
            assert ws.receive_json() == {"type": "stopped", "reason": "finished"}
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert asr.session is not None and asr.session.fed == ["我想买一副".encode("utf-8")]


def test_client_disconnect_aborts_session_without_ghost_stream():
    asr = FakeAsr()
    with TestClient(build_api(asr=asr)) as client:
        with client.websocket_connect("/commerce/voice/asr") as ws:
            ws.send_json({"buyer_id": "smartlect"})
            ws.send_bytes(b"pcm-frame")
    # 断开后服务端异步收尾，轮询确认会话被释放
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if asr.session is not None and asr.session.aborted:
            break
        time.sleep(0.05)
    assert asr.session is not None and asr.session.aborted


def test_asr_context_helper_dedupes_and_truncates():
    product = SimpleNamespace(brand="BrandA", category="耳机")
    same = SimpleNamespace(brand="BrandA", category="耳机")
    other = SimpleNamespace(brand="BrandB", category="键盘")
    context = build_asr_context([product, same, other], extra="术语：SKU")
    assert context.count("BrandA") == 1 and "BrandB" in context and "术语：SKU" in context
    # 限额极小时品牌段整体收缩，不残留半截标签；品类保留
    tight = build_asr_context([product, same, other], max_chars=12)
    assert "耳机" in tight and len(tight) <= 12 and not tight.endswith("品牌：")
