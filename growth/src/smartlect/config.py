"""Smartlect-only configuration; mock operation needs no credentials."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 18000
    model_mode: str = "mock"
    events_enabled: bool = False

    @classmethod
    def from_env(cls):
        events_enabled = os.getenv("SMARTLECT_GROWTH_EVENTS_ENABLED", "false").lower()
        if events_enabled not in {"true", "false"}:
            raise ValueError("SMARTLECT_GROWTH_EVENTS_ENABLED must be true or false")
        settings = cls(
            host=os.getenv("SMARTLECT_GROWTH_HOST", "127.0.0.1"),
            port=int(os.getenv("SMARTLECT_GROWTH_PORT", "18000")),
            model_mode=os.getenv("SMARTLECT_MODEL_MODE", "mock"),
            events_enabled=events_enabled == "true",
        )
        if not settings.host or not 1 <= settings.port <= 65535:
            raise ValueError("SMARTLECT_GROWTH_HOST/PORT must identify a valid bind address")
        if settings.model_mode not in {"mock", "live", "rule-fallback"}:
            raise ValueError("SMARTLECT_MODEL_MODE must be mock, live or rule-fallback")
        return settings
