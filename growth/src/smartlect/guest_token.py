"""Visitor session as HS256 JWT via PyJWT (exp/iat/jti/purpose).

Not a homemade cookie blob hash. Old 2-segment HMAC cookies stay in
``auth.IdentityBridge._verify`` so already-issued sessions keep working.
"""
from __future__ import annotations

import secrets
import time

import jwt


def issue_visitor_jwt(secret: bytes, visitor_id: str, *, ttl_seconds=86400 * 30) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": visitor_id,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": secrets.token_hex(16),
            "purpose": "visitor",
        },
        secret,
        algorithm="HS256",
        headers={"typ": "JWT"},
    )


def verify_visitor_jwt(secret: bytes, token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        if payload.get("purpose") != "visitor":
            raise ValueError("bad_purpose")
        if not isinstance(payload.get("jti"), str) or len(payload["jti"]) < 16:
            raise ValueError("bad_jti")
        if not isinstance(payload.get("sub"), str):
            raise ValueError("bad_sub")
        return payload
    except jwt.PyJWTError as error:
        raise ValueError("invalid_visitor_jwt") from error
    except (ValueError, TypeError) as error:
        raise ValueError("invalid_visitor_jwt") from error
