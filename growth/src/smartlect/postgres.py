"""Optional PostgreSQL 16 + pgvector for checkpoints and ANN.

Java commerce stays on MySQL. Tests without SMARTLECT_POSTGRES_DSN use MemorySaver
and lexical-only retrieval — that is a fallback, not a second advertised vector path.
"""
from __future__ import annotations

import os
from urllib.parse import quote_plus


def dsn_from_env(env=None) -> str | None:
    env = os.environ if env is None else env
    explicit = (env.get("SMARTLECT_POSTGRES_DSN") or "").strip()
    if explicit:
        return explicit
    host = (env.get("SMARTLECT_POSTGRES_HOST") or "").strip()
    if not host:
        return None
    port = int(env.get("SMARTLECT_POSTGRES_PORT") or 5432)
    user = env.get("SMARTLECT_POSTGRES_USER") or "smartlect"
    password = env.get("SMARTLECT_POSTGRES_PASSWORD") or ""
    database = env.get("SMARTLECT_POSTGRES_DATABASE") or "smartlect_growth"
    return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"


def available(env=None) -> bool:
    return bool(dsn_from_env(env))
