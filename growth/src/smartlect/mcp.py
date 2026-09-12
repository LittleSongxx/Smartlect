"""Minimal MCP Streamable HTTP server over the read-only half of the existing tool registry.

Scope is deliberately narrow. This implements JSON-RPC 2.0 `initialize`, `tools/list` and
`tools/call` on a single POST endpoint, which is what an external client needs to discover
and call Smartlect's read tools. It does not implement resources, prompts, sampling,
server-initiated requests, SSE streaming or session resumption, and it adds no dependency:
the tool schemas, permission checks and receipts are the same ones the Shopping agent uses,
so there is no second definition of a tool to drift from the first.

Only `read` tools are exposed. Proposals, memory writes and handoff stay off this surface
because they either move money or create records a caller outside the confirmation flow
must not be able to trigger. Exposing them would mean a second path to a transaction that
does not pass through the user's explicit confirmation.
"""
from smartlect.tools import REGISTRY, tool_schema

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
SERVER_INFO = {"name": "smartlect-shopping-read", "version": "1.0.0"}
EXPOSED_KINDS = ("read",)
# Read tools that still must not appear here:
#   load_skill      exists so the in-process agent can narrow its own prompt and permissions.
#                   It is not a business capability and an external client has no prompt to
#                   apply it to.
#   recommend_skus  saves a recommendation receipt that an A/B assignment and later exposure
#   search_skus     and click reports are attributed against; both names run the same
#   compare_skus    shopping retrieve. That receipt only means something when the caller is a
#                   display surface bound to report those events, which an MCP client is not,
#                   so serving them here would put unreported impressions into the
#                   attribution ledger. get_product_offer covers catalog lookup and reads
#                   Java product facts without recording anything.
INTERNAL_TOOLS = frozenset({"load_skill", "recommend_skus", "search_skus", "compare_skus"})


class JsonRpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def exposed_tools(actor):
    """Read tools the caller's own permissions already allow; never a wider set."""
    return {name: tool for name, tool in REGISTRY.items()
            if tool.kind in EXPOSED_KINDS and name not in INTERNAL_TOOLS
            and tool.permission in actor.permissions}


def tool_descriptors(actor):
    return [{"name": name, "description": tool.description,
             "inputSchema": tool_schema(tool.schema),
             "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
            for name, tool in sorted(exposed_tools(actor).items())]


def negotiate(requested):
    if requested is None:
        return PROTOCOL_VERSION
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    # The spec expects the server to answer with a version it does support rather than fail,
    # leaving the client to disconnect if it cannot accept that.
    return PROTOCOL_VERSION


async def handle(message, *, actor, call_tool):
    """Dispatch one JSON-RPC message. Returns None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise JsonRpcError(-32600, "invalid_request")
    method, identifier = message.get("method"), message.get("id")
    # Absent params is legal; wrong-typed params is not, so it must not be coerced away.
    params = message.get("params", {})
    if params is None:
        params = {}
    if not isinstance(method, str) or not isinstance(params, dict):
        raise JsonRpcError(-32600, "invalid_request")
    if identifier is None:
        # Notifications get no response at all, including for unknown methods.
        return None

    if method == "initialize":
        return {"protocolVersion": negotiate(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": "只读商品、政策与本人订单查询。价格、库存与订单状态以返回的Java事实为准；"
                                "本接口不能下单、付款、退款或转人工，交易须在用户确认流程内完成。"}
    if method == "tools/list":
        return {"tools": tool_descriptors(actor)}
    if method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "invalid_params")
        if name not in exposed_tools(actor):
            # Unknown and not-exposed are one answer on purpose: a caller should not be able
            # to probe which write tools exist behind this surface.
            raise JsonRpcError(-32602, "tool_not_available")
        try:
            receipt = await call_tool(name, arguments)
        except Exception as error:
            # A rejected call is a tool result, not a protocol error, so the client can show
            # it to the model and let it correct the arguments.
            return {"isError": True, "content": [{"type": "text", "text": _reason(error)}]}
        return {"isError": False, "content": [{"type": "text", "text": _text(receipt)}],
                "structuredContent": receipt}
    raise JsonRpcError(-32601, "method_not_found")


def _reason(error):
    # The client shows this to its model so it can correct the call, so the specific reason
    # matters more than the exception class.
    return getattr(error, "code", None) or str(error)[:160] or type(error).__name__


def _text(receipt):
    from smartlect.events import canonical
    return canonical(receipt.get("data") if isinstance(receipt, dict) and "data" in receipt else receipt)


def response(message, result=None, error=None):
    body = {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None}
    if error is not None:
        body["error"] = {"code": error.code, "message": error.message}
        if error.data is not None:
            body["error"]["data"] = error.data
    else:
        body["result"] = result
    return body
