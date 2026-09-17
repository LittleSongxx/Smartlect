"""MCP protocol layer only: no database, model or commerce calls."""
import json
from types import SimpleNamespace
import unittest

from smartlect import mcp
from smartlect.tools import REGISTRY


def actor(*permissions, subject_type='user'):
    return SimpleNamespace(permissions=permissions, subject_type=subject_type)


USER = actor('shopping:read', 'orders:read')
BUYER = actor('shopping:read', 'orders:read', 'orders:write')
GUEST = actor('shopping:read', subject_type='visitor')


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, method, params=None, *, who=USER, call_tool=None, identifier=1):
        message = {'jsonrpc': '2.0', 'id': identifier, 'method': method}
        if params is not None:
            message['params'] = params
        return await mcp.handle(message, actor=who, call_tool=call_tool)

    async def receipt(self, name, arguments):
        return {'data': {'echo': name}, 'tool_succeeded': True, 'command_status': 'command_accepted'}

    async def test_initialize_answers_with_a_version_it_supports(self):
        for requested, expected in (('2025-06-18', '2025-06-18'), ('2025-03-26', '2025-03-26'),
                                    (None, mcp.PROTOCOL_VERSION)):
            result = await self.call('initialize', {'protocolVersion': requested} if requested else {})
            self.assertEqual(result['protocolVersion'], expected)
            self.assertFalse(result.get('protocolVersionDowngraded'))
        unknown = await self.call('initialize', {'protocolVersion': '1999-01-01'})
        self.assertEqual(unknown['protocolVersion'], mcp.PROTOCOL_VERSION)
        self.assertTrue(unknown['protocolVersionDowngraded'])
        self.assertEqual(unknown['requestedProtocolVersion'], '1999-01-01')
        self.assertEqual(unknown['supportedProtocolVersions'], list(mcp.SUPPORTED_PROTOCOL_VERSIONS))
        self.assertEqual(unknown['capabilities'], {'tools': {'listChanged': False}})
        self.assertEqual(unknown['serverInfo']['name'], 'smartlect-shopping-read')

    async def test_no_write_tool_is_reachable_over_this_surface(self):
        writes = {name for name, tool in REGISTRY.items() if tool.kind != 'read'}
        self.assertTrue(writes, 'registry should still contain write tools')
        listed = {tool['name'] for tool in (await self.call('tools/list', who=BUYER))['tools']}
        self.assertFalse(listed & writes)
        self.assertFalse(listed & mcp.INTERNAL_TOOLS)
        # recommend_skus writes an attribution receipt whose exposures an MCP client cannot report.
        self.assertFalse({'recommend_skus', 'search_skus', 'compare_skus'} & listed)
        with self.assertRaises(mcp.JsonRpcError):
            await self.call('tools/call', {'name': 'recommend_skus', 'arguments': {'query': 'x'}},
                            who=BUYER, call_tool=self.receipt)
        for name in sorted(writes):
            # Unknown and not-exposed answer alike, so a caller cannot probe what exists.
            with self.subTest(tool=name), self.assertRaises(mcp.JsonRpcError) as raised:
                await self.call('tools/call', {'name': name, 'arguments': {}}, who=BUYER, call_tool=self.receipt)
            self.assertEqual(raised.exception.message, 'tool_not_available')
        with self.assertRaises(mcp.JsonRpcError) as unknown:
            await self.call('tools/call', {'name': 'no_such_tool', 'arguments': {}}, call_tool=self.receipt)
        self.assertEqual(unknown.exception.message, 'tool_not_available')

    async def test_tool_visibility_follows_the_caller_permissions(self):
        listed = {tool['name'] for tool in (await self.call('tools/list', who=GUEST))['tools']}
        self.assertIn('search_knowledge', listed)
        self.assertNotIn('get_my_orders', listed, 'a visitor has no orders:read')
        with self.assertRaises(mcp.JsonRpcError):
            await self.call('tools/call', {'name': 'get_my_orders', 'arguments': {}}, who=GUEST, call_tool=self.receipt)

    async def test_schemas_come_from_the_one_registry_so_they_cannot_drift(self):
        from smartlect.tools import tool_schema
        for descriptor in (await self.call('tools/list'))['tools']:
            tool = REGISTRY[descriptor['name']]
            self.assertEqual(descriptor['inputSchema'], tool_schema(tool.schema))
            self.assertEqual(descriptor['description'], tool.description)
            self.assertTrue(descriptor['annotations']['readOnlyHint'])

    async def test_a_rejected_call_is_a_tool_result_not_a_protocol_error(self):
        async def rejected(name, arguments):
            raise ValueError("product_scope_denied")
        result = await self.call('tools/call', {'name': 'get_product_offer', 'arguments': {'productId': 'p'}}, call_tool=rejected)
        self.assertTrue(result['isError'])
        self.assertIn('product_scope_denied', result['content'][0]['text'])
        ok = await self.call('tools/call', {'name': 'get_product_offer', 'arguments': {'productId': 'p'}}, call_tool=self.receipt)
        self.assertFalse(ok['isError'])
        self.assertEqual(ok['structuredContent']['command_status'], 'command_accepted')
        self.assertEqual(json.loads(ok['content'][0]['text']), {'echo': 'get_product_offer'})

    async def test_notifications_get_no_response_and_bad_frames_are_rejected(self):
        self.assertIsNone(await mcp.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                                           actor=USER, call_tool=None))
        self.assertIsNone(await mcp.handle({'jsonrpc': '2.0', 'method': 'notifications/unknown'},
                                           actor=USER, call_tool=None))
        for bad in ([], {'method': 'initialize'}, {'jsonrpc': '1.0', 'id': 1, 'method': 'initialize'},
                    {'jsonrpc': '2.0', 'id': 1, 'method': 5}, {'jsonrpc': '2.0', 'id': 1, 'method': 'x', 'params': []}):
            with self.subTest(frame=bad), self.assertRaises(mcp.JsonRpcError) as raised:
                await mcp.handle(bad, actor=USER, call_tool=None)
            self.assertEqual(raised.exception.code, -32600)
        with self.assertRaises(mcp.JsonRpcError) as missing:
            await self.call('tools/nope')
        self.assertEqual(missing.exception.code, -32601)
        for params in ({'name': 5}, {'name': 'get_product_offer', 'arguments': []}):
            with self.subTest(params=params), self.assertRaises(mcp.JsonRpcError) as invalid:
                await self.call('tools/call', params, call_tool=self.receipt)
            self.assertEqual(invalid.exception.code, -32602)

    async def test_response_envelope_carries_the_request_id(self):
        message = {'jsonrpc': '2.0', 'id': 'abc', 'method': 'tools/list'}
        body = mcp.response(message, result={'tools': []})
        self.assertEqual((body['jsonrpc'], body['id'], body['result']), ('2.0', 'abc', {'tools': []}))
        failed = mcp.response(message, error=mcp.JsonRpcError(-32601, 'method_not_found'))
        self.assertEqual(failed['error'], {'code': -32601, 'message': 'method_not_found'})
        self.assertNotIn('result', failed)


if __name__ == '__main__':
    unittest.main()
