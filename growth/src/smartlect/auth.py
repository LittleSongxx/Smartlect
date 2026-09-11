"""Java cookie introspection and signed read-only visitor sessions. No second login database."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Literal

import httpx
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict


class ActorContext(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    subject_type: Literal["user", "merchant", "visitor"]
    actor_id: str
    permissions: tuple[str, ...]
    session_id: str
    execution_scope_id: str = "store"
    visitor_id: str | None = None
    recommendation_subject_key: str | None = None

    def require(self, permission):
        if permission not in self.permissions:
            raise HTTPException(403, "permission_denied")


class IdentityBridge:
    def __init__(self, config, *, transport=None):
        self.url = f"http://127.0.0.1:{int(config['SMARTLECT_USER_PORT'])}/internal/identity/introspect"
        self.internal_token = config["SMARTLECT_INTERNAL_TOKEN"]
        self.secret = config["SMARTLECT_VISITOR_SECRET"].encode()
        if len(self.secret) < 32:
            raise ValueError("SMARTLECT_VISITOR_SECRET must contain at least 32 bytes")
        self.origins = frozenset(config.get("SMARTLECT_ALLOWED_ORIGINS", "").split(",")) - {""}
        self.transport = transport

    def _sign(self, purpose, payload):
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        signature = hmac.new(self.secret, f"{purpose}:{encoded}".encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def _verify(self, purpose, token):
        try:
            if len(token) > 2048:
                raise ValueError()
            encoded, signature = token.split(".")
            expected = hmac.new(self.secret, f"{purpose}:{encoded}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if type(payload["expires"]) is not int or payload["expires"] <= time.time():
                raise ValueError()
            return payload
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(401, "invalid_session_proof") from None

    async def authenticate(self, request: Request, response: Response, *, realm="user"):
        cookie_name = "adminToken" if realm == "merchant" else "token"
        for name in (cookie_name, "smartlect_visitor"):
            occurrences = sum(part.strip().split("=", 1)[0] == name
                              for header in request.headers.getlist("cookie") for part in header.split(";"))
            if occurrences > 1:
                raise HTTPException(401, "ambiguous_session_cookie")
        token = request.cookies.get(cookie_name)
        if token is not None:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,512}", token):
                raise HTTPException(401, "invalid_session")
            try:
                async with httpx.AsyncClient(transport=self.transport, timeout=5, trust_env=False) as client:
                    result = await client.post(self.url, json={"realm": realm}, headers={
                        "X-Internal-Token": self.internal_token, "Cookie": f"{cookie_name}={token}"})
                if result.status_code == 401:
                    raise HTTPException(401, "invalid_session")
                result.raise_for_status()
                envelope = result.json()
                if envelope.get("status") != "success":
                    raise HTTPException(401, "invalid_session")
                data = envelope["data"]
                if data["subjectType"] != realm or not data["actorId"] or not data["sessionId"]:
                    raise ValueError()
                visitor_id = None
                if realm == 'user' and request.cookies.get('smartlect_visitor'):
                    try:
                        visitor_id = self.visitor_id(request.cookies['smartlect_visitor'])
                    except HTTPException:
                        response.delete_cookie('smartlect_visitor')  # A stale optional visitor proof cannot invalidate Java login.
                return ActorContext(subject_type=data["subjectType"], actor_id=data["actorId"],
                                    permissions=tuple(data["permissions"]), session_id=data["sessionId"], visitor_id=visitor_id)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise HTTPException(503, "identity_unavailable") from None
        if realm == "merchant":
            raise HTTPException(401, "login_required")
        visitor = request.cookies.get("smartlect_visitor")
        if visitor:
            identifier = self.visitor_id(visitor)
        else:
            identifier = secrets.token_hex(16)
            visitor = self._sign("visitor", {"id": identifier, "expires": int(time.time()) + 86400 * 30})
            response.set_cookie("smartlect_visitor", visitor, httponly=True, samesite="lax", max_age=86400 * 30,
                                secure=request.url.scheme == "https")
        return ActorContext(subject_type="visitor", actor_id=identifier, permissions=("shopping:read",),
                            session_id=hashlib.sha256(visitor.encode()).hexdigest(), visitor_id=identifier)

    def visitor_id(self, proof):
        identifier = self._verify('visitor', proof).get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier):
            raise HTTPException(401, 'invalid_visitor')
        return identifier

    def csrf_token(self, actor):
        return self._sign("csrf", {"actor": actor.actor_id, "type": actor.subject_type,
                                  "session": actor.session_id, "scope": actor.execution_scope_id, "nonce": secrets.token_hex(12),
                                  "expires": int(time.time()) + 3600})

    def require_csrf(self, request, actor):
        if request.headers.get("origin") not in self.origins:
            raise HTTPException(403, "origin_denied")
        try:
            payload = self._verify("csrf", request.headers.get("x-csrf-token", ""))
        except HTTPException:
            raise HTTPException(403, "csrf_denied") from None
        if (payload.get("actor"), payload.get("type"), payload.get("session"), payload.get("scope")) != (
                actor.actor_id, actor.subject_type, actor.session_id, actor.execution_scope_id):
            raise HTTPException(403, "csrf_denied")
