"""Tiny in-process TTL caches. One uvicorn process serves all traffic, so plain
dicts with a monotonic deadline are enough; no cross-process coherence required."""

import time


class TtlCache:
    """Bounded key->value store; entries expire lazily and the earliest deadline is evicted first."""

    def __init__(self, maxsize, ttl_seconds):
        if maxsize < 1 or ttl_seconds <= 0:
            raise ValueError("invalid_cache_bounds")
        self.maxsize, self.ttl = maxsize, ttl_seconds
        self._entries = {}  # key -> (expires_at, value)

    def get(self, key):
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry[0]:
            self._entries.pop(key, None)
            return None
        return entry[1]

    def put(self, key, value):
        if len(self._entries) >= self.maxsize:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            self._entries.pop(oldest, None)
        self._entries[key] = (time.monotonic() + self.ttl, value)
