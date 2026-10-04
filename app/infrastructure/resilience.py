# -*- coding: utf-8 -*-
"""ToolResilienceMiddleware

工具韧性中间件（复用 2.0 ToolMiddlewareBase 的洋葱式拦截）：

    超时：单次工具执行超过阈值即中断，返回结构化 error chunk，不把异常抛穿到 Agent 循环
    熔断：按工具名统计连续失败，达阈值后打开熔断，reset_seconds 内直接短路返回降级提示；
          冷却期满转半开，同一时刻只放行**一个**探测请求（探测在飞期间其余调用拒绝），
          成功即闭合、失败即重新打开；探测结果未知（调用被取消）只清除探测标志，
          probe_timeout_seconds 兜底防止探测标志卡死熔断

设计取舍：熔断状态按 (工具名) 维度进程内共享（CircuitBreakerRegistry），
让同一工具在不同 Agent 实例间共享故障视图；降级返回始终是 ToolChunk(ERROR)，
Agent 能看到失败原因并如实告知买家，不会误以为工具成功。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolBase, ToolChunk, ToolMiddlewareBase

from app.infrastructure.context import ShoppingContext
from app.infrastructure.eventbus import TradeEventBus
from app.infrastructure.transient import is_transient_error

logger = logging.getLogger(__name__)

# 工具超时分级（秒）：检索/知识库偏长，订单要快，子代理调度最宽松
DEFAULT_TIMEOUTS: dict[str, float] = {
    "product_search_tool": 15.0,
    "category_insight_tool": 15.0,
    "web_search_tool": 20.0,
    "create_order_tool": 10.0,
    "query_order_tool": 10.0,
    "cancel_order_tool": 10.0,
    "remember_preference_tool": 90.0,
    "update_preference_tool": 90.0,
    "task_dispatch": 180.0,
}
_FALLBACK_TIMEOUT = 30.0


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    opened_at: Optional[float] = None
    half_open_probing: bool = False
    # 半开探测的在飞截止时刻：探测调用超时/被取消且未回报时，超时后允许新探测
    probe_deadline: Optional[float] = None

    @property
    def status(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.half_open_probing else "open"


@dataclass
class CircuitBreakerRegistry:
    """进程内共享的熔断状态表（按工具名）。"""

    failure_threshold: int = 3
    reset_seconds: float = 60.0
    # 应大于最慢工具超时（task_dispatch 180s），否则长探测会被并行再放一个
    probe_timeout_seconds: float = 300.0
    _states: dict[str, _CircuitState] = field(default_factory=dict)

    def _state(self, tool_name: str) -> _CircuitState:
        return self._states.setdefault(tool_name, _CircuitState())

    def status(self, tool_name: str) -> str:
        return self._state(tool_name).status

    def allow(self, tool_name: str, now: Optional[float] = None) -> bool:
        """是否放行本次调用；冷却期满放行**单个**探测，其余调用拒绝。

        旧实现对冷却期满的每个调用都放行（自称"放一次探测"），
        下游仍宕机时半开窗口内的全部请求都各等满超时，熔断保护失效。
        """
        state = self._state(tool_name)
        if state.opened_at is None:
            return True
        current = now or time.monotonic()
        if current - state.opened_at < self.reset_seconds:
            return False
        if state.half_open_probing and (state.probe_deadline is None or current < state.probe_deadline):
            return False
        state.half_open_probing = True
        state.probe_deadline = current + self.probe_timeout_seconds
        return True

    def record_success(self, tool_name: str) -> None:
        self._states[tool_name] = _CircuitState()

    def record_failure(self, tool_name: str, now: Optional[float] = None) -> None:
        state = self._state(tool_name)
        if state.half_open_probing:
            # 半开探测再次失败：重新打开并重置冷却计时
            state.opened_at = now or time.monotonic()
            state.half_open_probing = False
            state.probe_deadline = None
            return
        state.consecutive_failures += 1
        if state.consecutive_failures >= self.failure_threshold:
            state.opened_at = now or time.monotonic()

    def record_abandoned(self, tool_name: str) -> None:
        """调用被取消（探测结果未知）：只清除探测标志，不改变熔断开合。

        取消不算失败——用户点"停止"不应把半开探测重新打回冷却期；
        但探测名额必须释放，否则后续调用要等到 probe 超时才能再探测。
        """
        state = self._state(tool_name)
        if state.half_open_probing:
            state.half_open_probing = False
            state.probe_deadline = None


class ToolResilienceMiddleware(ToolMiddlewareBase):
    """工具超时 + 熔断中间件。

    熔断注册表可以是进程内的 `CircuitBreakerRegistry`，
    也可以是 Redis 支撑的 `SharedCircuitBreakerRegistry`（跨实例共享）。
    后者的读写是异步的，故这里统一走 `_allow` / `_record_*` 三个适配函数：
    注册表提供 `*_async` 时优先 await 它，否则回落同步方法。
    """

    def __init__(
        self,
        registry: CircuitBreakerRegistry,
        bus: Optional[TradeEventBus] = None,
        timeouts: Optional[dict[str, float]] = None,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._timeouts = timeouts or DEFAULT_TIMEOUTS

    def _timeout_for(self, tool_name: str) -> float:
        return self._timeouts.get(tool_name, _FALLBACK_TIMEOUT)

    def _publish_circuit(self, tool_name: str, circuit: str, detail: str) -> None:
        if self._bus is None:
            return
        self._bus.publish(
            ShoppingContext.current_session_id(),
            "tool.result",
            {"tool": tool_name, "circuit": circuit, "error": detail},
        )

    async def on_tool_call(
        self,
        tool: ToolBase,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[ToolChunk, None]],
    ) -> AsyncGenerator[ToolChunk, None]:
        tool_name = tool.name

        if not await _allow(self._registry, tool_name):
            detail = f"{tool_name} 连续失败已熔断，暂不可用，请稍后再试或改用其他方式"
            logger.warning("工具熔断短路：%s", tool_name)
            self._publish_circuit(tool_name, "open", detail)
            yield ToolChunk(
                content=[TextBlock(type="text", text=f"[error] {detail}")],
                state=ToolResultState.ERROR,
            )
            return

        timeout = self._timeout_for(tool_name)
        chunks: list[ToolChunk] = []
        try:
            # 先在超时保护内收集全部 chunk，再对外 yield：
            # 保证超时能被拦在中间件内部，不会把半截流交给 Agent
            async def _collect() -> list[ToolChunk]:
                collected: list[ToolChunk] = []
                async for chunk in next_handler(**input_kwargs):
                    collected.append(chunk)
                return collected

            chunks = await asyncio.wait_for(_collect(), timeout=timeout)
        except asyncio.TimeoutError:
            await _record_failure(self._registry, tool_name)
            detail = f"{tool_name} 执行超过 {timeout:.0f} 秒已中断"
            logger.warning("工具超时：%s（%.0fs）", tool_name, timeout)
            self._publish_circuit(tool_name, await _status(self._registry, tool_name), detail)
            yield ToolChunk(
                content=[TextBlock(type="text", text=f"[error] {detail}")],
                state=ToolResultState.ERROR,
            )
            return
        except asyncio.CancelledError:
            # 取消时探测结果未知：释放半开探测名额（不重新打开、不闭合），
            # 否则用户点"停止"会把半开探测打回冷却期，或让探测标志卡到 probe 超时。
            try:
                await _record_abandoned(self._registry, tool_name)
            except Exception as err:  # noqa: BLE001 —— 清理失败不能覆盖原始取消
                logger.warning("工具取消后清理熔断探测未成功：%s（%s）", tool_name, err)
            raise
        except Exception as err:  # noqa: BLE001 —— 未捕获异常也计入失败并降级
            await _record_failure(self._registry, tool_name)
            detail = f"{tool_name} 执行异常：{err}"
            logger.warning("工具异常：%s（%s）", tool_name, err)
            self._publish_circuit(tool_name, await _status(self._registry, tool_name), detail)
            yield ToolChunk(
                content=[TextBlock(type="text", text=f"[error] {detail}")],
                state=ToolResultState.ERROR,
            )
            return

        # 只有瞬时基础设施错误才计入熔断。参数校验、目的国不支持、订单不存在等
        # 确定性业务错误说明工具本身仍然健康，不能让一批坏请求毒死后续正常流量。
        if chunks and chunks[-1].state == ToolResultState.ERROR and _is_transient_tool_error(chunks[-1]):
            await _record_failure(self._registry, tool_name)
        else:
            await _record_success(self._registry, tool_name)

        for chunk in chunks:
            yield chunk


def _is_transient_tool_error(chunk: ToolChunk) -> bool:
    texts: list[str] = []
    for block in chunk.content or []:
        if isinstance(block, dict):
            texts.append(str(block.get("text", "")))
        else:
            texts.append(str(getattr(block, "text", "")))
    return is_transient_error(RuntimeError("\n".join(texts)))


# ---- 注册表适配：共享实现的读写是异步的，本地实现是同步的 ----


async def _allow(registry: Any, tool_name: str) -> bool:
    if hasattr(registry, "allow_async"):
        return await registry.allow_async(tool_name)
    return registry.allow(tool_name)


async def _record_failure(registry: Any, tool_name: str) -> None:
    if hasattr(registry, "record_failure_async"):
        await registry.record_failure_async(tool_name)
        return
    registry.record_failure(tool_name)


async def _record_abandoned(registry: Any, tool_name: str) -> None:
    if hasattr(registry, "record_abandoned_async"):
        await registry.record_abandoned_async(tool_name)
        return
    registry.record_abandoned(tool_name)


async def _record_success(registry: Any, tool_name: str) -> None:
    if hasattr(registry, "record_success_async"):
        await registry.record_success_async(tool_name)
        return
    registry.record_success(tool_name)


async def _status(registry: Any, tool_name: str) -> str:
    if hasattr(registry, "status_async"):
        return await registry.status_async(tool_name)
    return registry.status(tool_name)
