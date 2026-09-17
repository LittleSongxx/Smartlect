"""Token counts for chunking and context windows. Not a billing source.

Uses tiktoken cl100k_base as a stable offline tokenizer. Provider `usage` remains
authoritative for actual model consumption. CJK×2 is not a hard cap.
"""
from __future__ import annotations

_enc = None


def encoding():
    global _enc
    if _enc is None:
        import tiktoken
        _enc = tiktoken.get_encoding("cl100k_base")
    return _enc


def count_tokens(text) -> int:
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    return len(encoding().encode(text))


def truncate_tokens(text, limit) -> str:
    if not text or limit <= 0:
        return ""
    pieces = encoding().encode(text)
    if len(pieces) <= limit:
        return text
    return encoding().decode(pieces[:limit])
