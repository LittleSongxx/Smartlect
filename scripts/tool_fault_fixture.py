"""Root-operated loopback fixture for frozen tool-013; never a production switch.

Runs the actual app/Shopping/persistent stores and Java identity bridge, but chat
HTTP uses a local MockTransport. No model network request or real model capability.
"""
import argparse
import asyncio
import os

import httpx
import uvicorn
from fastapi import HTTPException

from runtime import ENV_FILE, model_env, parse_env
from smartlect.app import create_app
from smartlect.attribution import AttributionStore
from smartlect.auth import IdentityBridge
from smartlect.config import Settings
from smartlect.events import connect_from_env
from smartlect.provider import Provider, _callback
from smartlect.state import SessionStore


class InjectedProvider(Provider):
    def __init__(self, config, fault):
        if fault not in {'timeout', 'invalid_json'}:
            raise ValueError('unsupported_local_fault')
        self.fault = fault
        def transport(request):
            if fault == 'timeout':
                raise httpx.ReadTimeout('local_injected_transport_timeout', request=request)
            return httpx.Response(200, json={'model': config.get('SMARTLECT_MODEL_ID', 'qwen3.7-plus'),
                'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{ invalid local fixture JSON'}}]})
        super().__init__(config, transport=httpx.MockTransport(transport))

    async def chat(self, messages, *, on_trace=None, **options):
        async def trace(record):
            record = {**record, 'model_mode': 'injected_transport', 'fault': self.fault,
                'real_model_called': False, 'fixture_version': 'tool-provider-fault-v1'}
            await _callback(on_trace, record)
        return await super().chat(messages, on_trace=trace, **options)


def fixture_app(config, scope, actor_id, fault):
    attribution = AttributionStore(connect_from_env, secret=config.get('SMARTLECT_ATTRIBUTION_SECRET'))
    class ScopedIdentity(IdentityBridge):
        async def authenticate(self, request, response, *, realm='user'):
            actor = await super().authenticate(request, response, realm=realm)
            actor = await asyncio.to_thread(attribution.resolve_actor, actor)
            if actor.subject_type != 'user' or actor.actor_id != actor_id or actor.execution_scope_id != scope:
                raise HTTPException(403, 'fixture_scope_or_actor_denied')
            return actor
    app = create_app(Settings(model_mode='live', events_enabled=False), config=config, store=SessionStore(),
        identity=ScopedIdentity(config), attribution=attribution, provider=InjectedProvider(config, fault))
    @app.middleware('http')
    async def only_question_paths(request, call_next):
        from fastapi.responses import JSONResponse
        path = request.url.path
        allowed = (request.method == 'GET' and (path in {'/health', '/fixture-health', '/api/assistant/session'} or path.startswith('/api/assistant/runs/'))
                   or request.method == 'POST' and (path == '/api/assistant/conversations' or path.startswith('/api/assistant/conversations/') and path.endswith('/messages')))
        if not allowed: return JSONResponse(status_code=403, content={'error': 'fixture_readonly_question_paths'})
        return await call_next(request)
    @app.get('/fixture-health')
    async def fixture_health():
        return {'status': 'ok', 'pid': os.getpid(), 'scope': scope, 'actor_id': actor_id,
            'fault': fault, 'fixture_version': 'tool-provider-fault-v1', 'real_model_called': False}
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True)
    parser.add_argument('--actor-id', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--fault', choices=['timeout', 'invalid_json'], default='timeout')
    args = parser.parse_args(argv)
    if args.scope == 'store' or not 1024 <= args.port <= 65535: parser.error('Dedicated registered scope and nonprivileged port required')
    config = {**parse_env(ENV_FILE), **model_env()}
    if config.get('SMARTLECT_PAYMENT_MODE') != 'mock': parser.error('Mock payment is required')
    for key, value in config.items():
        if key.startswith(('SMARTLECT_GROWTH_MYSQL_', 'SMARTLECT_MYSQL_')): os.environ[key] = value
    # Never use real provider credentials, even though the transport cannot leave the process.
    config['SMARTLECT_MODEL_API_KEY'] = 'local-fault-fixture-only'
    config.pop('SMARTLECT_EMBEDDING_API_KEY', None)
    config['SMARTLECT_ALLOWED_ORIGINS'] = 'http://127.0.0.1:' + str(args.port)
    with connect_from_env() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT execution_scope_id FROM execution_resource WHERE resource_type='user' AND resource_id=%s AND execution_scope_id=%s", (args.actor_id, args.scope))
        if not cursor.fetchone(): parser.error('Actor is not registered to the fixture scope')
    uvicorn.run(fixture_app(config, args.scope, args.actor_id, args.fault), host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
