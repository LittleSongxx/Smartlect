# -*- coding: utf-8 -*-
"""output_guard —— L4：输出审核

最后一道闸：Agent 的最终回复推给买家之前，检查是否夹带了内部实现信息。
命中即脱敏，并把 (是否安全) 回给调用方去发告警事件——脱敏动作本身不阻断回复，
否则一次误判就等于整轮对话失败。

**刻意收窄的范围**（与 16-6 章文档的差异，如实记录）：

    1. 文档示例里有 `item_id`，本项目 schema 中不存在该字段，故不纳入；
    2. `product_id`（如 P1001）**不脱敏**——它本就随商品卡通过 tool.result 事件
       下发给前端渲染，属于对外契约的一部分，脱敏反而会破坏正常回复；
    3. 内部工具名按真实工具集逐个列出，不用 `\\w+_tool` 这类宽泛模式，
       避免把买家可见的正常措辞误伤。

判据只有一条：**脱敏对象必须是买家侧无需知道、且泄露有害的东西**。
"""
from __future__ import annotations

import re

REDACTED = "[已脱敏]"

# 真实存在的内部工具名（与 app/application/tools/ 一致）
_INTERNAL_TOOLS = (
    "product_search_tool",
    "category_insight_tool",
    "web_search_tool",
    "create_order_tool",
    "query_order_tool",
    "cancel_order_tool",
    "remember_preference_tool",
    "task_dispatch",
)

SENSITIVE_PATTERNS: list[str] = [
    # 会话内部 ID
    r"shopping_session_id\s*[:=]\s*[\w-]+",
    # API Key 形态
    r"sk-[a-zA-Z0-9]{20,}",
    # 内部服务地址（容器网络内主机名）
    r"https?://(?:vllm|reranker|qdrant|redis|opensearch)(?::\d+)?(?:/\S*)?",
    # 内部工具名
    r"\b(?:" + "|".join(_INTERNAL_TOOLS) + r")\b",
]

_compiled = [re.compile(pattern) for pattern in SENSITIVE_PATTERNS]


def _mask_text(text: str) -> str:
    """对全文执行全部敏感模式替换，返回脱敏后文本。"""
    cleaned = text
    for pattern in _compiled:
        cleaned, _ = pattern.subn(REDACTED, cleaned)
    return cleaned


def audit_output(text: str) -> tuple[bool, str]:
    """审核最终输出。

    Returns:
        (是否安全, 处理后的文本)。安全 = 未命中任何敏感模式；
        命中时文本已就地脱敏，可直接下发。
    """
    if not text:
        return True, text

    safe = True
    cleaned = text
    for pattern in _compiled:
        cleaned, count = pattern.subn(REDACTED, cleaned)
        if count:
            safe = False
    return safe, cleaned


class StreamingMasker:
    """流式增量脱敏：为 token.delta / TEXT_MESSAGE_CONTENT 这类增量流提供与
    `audit_output` 同源的掩码保证——旧实现只守卫 final text，流式增量会先一步
    把敏感内容实时推给买家。

    算法：每次 push 对**全量缓冲**重跑掩码（完整匹配立即替换），再计算**动态
    扣留长度**后放行。扣留依据是"敏感模式字面触发串"（每个敏感模式的匹配都
    必然以这些字面量开头）：

        1. 缓冲尾部是某触发串的真前缀 → 扣留该前缀长度（模式可能正在到达）；
        2. 缓冲中存在完整触发串 → 从其起点扣留到末尾（匹配可能仍在延伸，
           如 session_id 的值、URL 的路径还在陆续到达）。

    已放行前缀因此永远不含"事后才补全"的匹配起点；掩码替换只发生在扣留区
    之后，前缀稳定、按已放行长度差量输出。干净文本的扣留为 0（即时流式），
    只有疑似敏感内容在途时才暂停放行，流结束 flush 释放余量。
    """

    # 每个敏感模式匹配的字面起始串：模式1/2/3 分别是 id 前缀、密钥前缀、
    # URL 协议头；模式4（内部工具名）的每个分支都是完整字面量。
    _TRIGGERS: tuple[str, ...] = ("shopping_session_id", "sk-", "http", *_INTERNAL_TOOLS)

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted = 0

    def _hold_length(self, masked: str) -> int:
        hold = 0
        for trigger in self._TRIGGERS:
            # 尾部是触发串的真前缀：模式前缀正在到达
            for length in range(min(len(masked), len(trigger) - 1), 0, -1):
                if masked.endswith(trigger[:length]):
                    hold = max(hold, length)
                    break
            # 完整触发串在场：匹配可能仍在延伸，从其起点扣留
            position = masked.rfind(trigger)
            if position != -1:
                hold = max(hold, len(masked) - position)
        return hold

    def push(self, delta: str) -> str:
        """追加一段增量，返回本次可安全放行的文本（可为空串）。"""
        if not delta:
            return ""
        self._buffer += delta
        masked = _mask_text(self._buffer)
        safe_end = len(masked) - self._hold_length(masked)
        if safe_end <= self._emitted:
            return ""
        output = masked[self._emitted:safe_end]
        self._emitted = safe_end
        return output

    def flush(self) -> str:
        """流结束时释放扣留的尾部（先掩码）。"""
        masked = _mask_text(self._buffer)
        output = masked[self._emitted:]
        self._emitted = len(masked)
        return output
