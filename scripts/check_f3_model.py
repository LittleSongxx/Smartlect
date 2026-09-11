"""Live recommendation branch coverage, not a ranking-effect or held-out evaluation."""
import json
from pathlib import Path
import time
import uuid

import httpx

from runtime import ENV_FILE, parse_env
from smartlect.commerce import CommerceClient


def main():
    config = parse_env(ENV_FILE)
    java = CommerceClient(config)
    base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
    report = {'model_mode': 'live', 'payment_mode': 'not_executed', 'assignments_observed': [],
              'selection_policy': 'First treatment assignment among owned demo users 78–87; branch coverage, not outcome selection',
              'evidence_scope': 'One bounded real Shopping + semantic-rerank capability run, not evaluation scores'}
    output = Path('artifacts/f3-live-recommendation.json')

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    with httpx.Client(base_url=base, timeout=35, trust_env=False) as client:
        for index in range(78, 88):
            user = java.request('admin', '/internal/demo/session', form={'userIndex': index, 'password': config['SMARTLECT_DEMO_PASSWORD']})
            client.cookies.clear(); client.cookies.set('token', user['token'])
            session = client.get('/api/assistant/session'); session.raise_for_status()
            auth = session.json()
            response = client.get('/api/assistant/recommendations', params={'query': '数码', 'max_price_cents': 2000, 'limit': 4})
            response.raise_for_status(); recommendation = response.json()
            report['assignments_observed'].append({'user_index': index, **recommendation['assignment']})
            save()
            if recommendation['assignment']['group'] == 'treatment':
                break
        else:
            raise AssertionError('No treatment assignment in bounded fixture range; no model outcome observed')
        headers = {'Origin': base, 'X-CSRF-Token': auth['csrf_token']}
        response = client.post('/api/assistant/conversations', headers=headers, json={})
        response.raise_for_status(); conversation = response.json()['conversation_id']
        response = client.post(f'/api/assistant/conversations/{conversation}/messages', headers=headers,
            json={'message_id': uuid.uuid4().hex, 'text': '请推荐20元以内实际有货的数码商品，显示SKU卡和简短理由；请不要下单。'})
        response.raise_for_status(); identifier = response.json()['agent_run_id']
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline:
            response = client.get('/api/assistant/runs/' + identifier); response.raise_for_status()
            run = response.json()
            if run['state'] not in {'CREATED', 'RUNNING'}:
                break
            time.sleep(.5)
        report.update(run=run, conversation_id=conversation)
        save()
        assert run['state'] == 'COMPLETED' and run['result']['model_mode'] == 'live'
        products = run['result']['products']
        assert products and all(p['ranking_mode'] == 'content_llm' and p['stock'] > 0 and p['price_cents'] <= 2000 for p in products)
        assert any(t['prompt_version'] == 'recommendation-rerank-v1' and t['status'] == 'succeeded' for t in run['context']['model_attempts'])
        assert run['context']['model_calls'] <= 6 and run['context']['tool_calls'] <= 10
        assert not run['result']['proposal']
        report['passed'] = True
        save()
        print(json.dumps({'passed': True, 'ranking_mode': 'content_llm', 'products': len(products),
                          'model_calls': run['context']['model_calls'], 'agent_run_id': identifier}))


if __name__ == '__main__':
    main()
