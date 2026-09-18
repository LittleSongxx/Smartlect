"""Bounded HTTP access to Java; this module has no database connection."""
import json
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import httpx


class CommerceError(RuntimeError):
    pass


# Internal paths referenced from more than one call site; single source shared with tools and routes.
PRODUCT_SNAPSHOT_BATCH_PATH = "/internal/product/snapshotBatch"
STOCK_BATCH_PATH = "/internal/stock/getBatch"
ORDER_ACTION_STATUS_PATH = "/internal/order/commerce/v2/actionStatus"


class CommerceRejected(CommerceError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class AsyncCommerceClient:
    """Internal transport for registered tools; identity is never taken from tool arguments."""
    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport
        self._client = None  # shared; AsyncClient() construction loads CA certs, never per call

    async def request(self, service, path, *, actor=None, data=None, key=None):
        if service not in {"user", "product", "stock", "order", "coupon", "pay"} or not path.startswith("/internal/"):
            raise ValueError("Unregistered commerce destination")
        headers = {"X-Internal-Token": self.config["SMARTLECT_INTERNAL_TOKEN"]}
        if actor is not None and actor.subject_type == "user":
            headers["X-Smartlect-User-Id"] = actor.actor_id
        if key:
            headers["Idempotency-Key"] = key
        url = f"http://127.0.0.1:{int(self.config[f'SMARTLECT_{service.upper()}_PORT'])}{path}"
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(transport=self.transport, timeout=10, trust_env=False)
            response = await self._client.post(url, json=data or {}, headers=headers)
        except httpx.HTTPError:
            raise CommerceError("commerce_outcome_unknown") from None
        if response.status_code >= 500:
            raise CommerceError("commerce_outcome_unknown")
        try:
            result = json.loads(response.content, parse_float=Decimal)
        except ValueError:
            raise CommerceError("commerce_outcome_unknown") from None
        if not isinstance(result, dict):
            raise CommerceError("commerce_outcome_unknown")
        if response.status_code >= 400 or result.get("status") != "success":
            reason = "RECONFIRM_REQUIRED" if "RECONFIRM_REQUIRED" in str(result.get("info", "")) else "commerce_rejected"
            raise CommerceRejected(response.status_code if response.status_code >= 400 else result.get("code", 409), reason)
        return result.get("data")


class CommerceClient:
    def __init__(self, config):
        self.config = config

    def request(self, service, path, *, data=None, form=None, session=None, key=None):
        port = int(self.config[f"SMARTLECT_{service.upper()}_PORT"])
        headers = {}
        if path.startswith("/internal/"):
            headers["X-Internal-Token"] = self.config["SMARTLECT_INTERNAL_TOKEN"]
            if session:
                headers["X-Smartlect-User-Id"] = session["userId"]
        elif session:
            headers["token"] = session["token"]
        if key:
            headers["Idempotency-Key"] = key
        if form is not None:
            body = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode() if data is not None else b""
            headers["Content-Type"] = "application/json"
        request = Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=10) as response:
                result = json.load(response, parse_float=Decimal)
        except HTTPError as error:
            raise CommerceError(f"{service}{path}: HTTP {error.code}: {error.read().decode()[:500]}") from error
        if result.get("status") != "success":
            raise CommerceError(f"{service}{path}: {result.get('code')} {result.get('info')}")
        return result.get("data")
