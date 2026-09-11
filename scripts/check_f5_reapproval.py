"""Continue an owned F5 scope through explicit replacement approval, using the rule planner.

Existing simulated CPC and failed development evidence are retained. The local
driver represents merchant approval and one new simulated advertising visitor.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import traceback
import uuid

import httpx

from check_f4 import login_merchant
from check_f3 import json_value
from demo import wait_for
from runtime import ENV_FILE, ROOT, parse_env
from smartlect.commerce import CommerceClient
from smartlect.events import canonical


def main(source, output):
    if output.exists():
        raise ValueError('Use a new output path; existing evidence is retained')
    raw = source.read_bytes()
    prior = json.loads(raw)
    evidence = {'phase': 'F5 reapproval', 'status': 'RUNNING', 'source': str(source),
                'source_sha256': hashlib.sha256(raw).hexdigest(), 'model_mode': 'rule-fallback',
                'payment_mode': 'mock', 'advertising_mode': 'persisted_simulated_cpc',
                'execution_scope_id': prior['execution_scope_id'], 'steps': []}

    def save():
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')

    def record(label, value):
        evidence['steps'].append({'label': label, 'value': value})
        save()
        return value

    save()
    try:
        config = parse_env(ENV_FILE)
        assert config['SMARTLECT_PAYMENT_MODE'] == 'mock'
        java = CommerceClient(config)
        base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
        with httpx.Client(base_url=base, timeout=25, trust_env=False) as merchant:
            headers = login_merchant(merchant, config)
            selected = merchant.post('/admin-api/assistant/scopes/select',
                json={'execution_scope_id': prior['execution_scope_id']}, headers=headers)
            assert selected.status_code == 200
            headers = {'Origin': base, 'X-CSRF-Token': selected.json()['csrf_token']}

            def get(path):
                response = merchant.get('/admin-api/assistant/' + path)
                assert response.status_code == 200, 'Read refused: ' + path
                return response.json()

            def post(path, request):
                record('request:' + path, request)
                response = merchant.post('/admin-api/assistant/' + path, json=request, headers=headers)
                record('response:' + path, {'http_status': response.status_code, 'body': response.json()})
                assert response.status_code == 200, 'Write refused: ' + path
                return response.json()

            initial = record('initial_ads', get('ads'))
            assert len(initial['campaigns']) == 1 and initial['account']['spent_cents'] == 1
            assert initial['campaigns'][0]['status'] == initial['creatives'][0]['status'] == 'ACTIVE'
            old_grant = next(g for g in initial['grants'] if g['grant_id'] == initial['account']['grant_id'])
            assert not old_grant['revoked_at']
            assert datetime.fromisoformat(old_grant['envelope']['valid_until'].replace('Z', '+00:00')) > datetime.now(timezone.utc)
            cap = initial['account']['budget_cap_cents'] + 100
            catalog = get('ads/catalog')['items']
            sku = next(s for s in catalog if s['product_id'] == prior['java_manifest']['products'][1] and s['stock'] > 0)
            campaign = post('ads/campaigns', {'campaign_id': uuid.uuid4().hex, 'name': 'F5 explicit reapproval branch',
                'product_id': sku['product_id'], 'sku_key': sku['sku_key'], 'budget_cents': 0, 'cpc_cents': 1})
            creative = post('ads/creatives', {'creative_id': uuid.uuid4().hex,
                'campaign_id': campaign['campaign_id'], 'copy_text': '推广：核对商品规格后再选择。'})
            run = post('merchant/runs', {'request_id': uuid.uuid4().hex, 'objective': old_grant['envelope']['objective'],
                'mode': 'rule', 'product_scope': old_grant['envelope']['product_scope'], 'planned_budget_cents': cap})
            completed = wait_for(lambda: get('merchant/runs/' + run['agent_run_id']),
                lambda r: r['state'] not in {'CREATED', 'RUNNING'}, 'rule plan', timeout=95)
            state = get('merchant')
            plan = next(p for p in state['plans'] if p['agent_run_id'] == run['agent_run_id'])
            record('rule_run', completed)
            record('unapproved_plan', plan)
            assert completed['context']['model_calls'] == 0 and plan['spec']['model_mode'] == 'rule-fallback'
            assert plan['status'] == 'WAIT_APPROVAL' and plan['grant_id'] is None and not plan['action_receipts']
            assert plan['authorization']['reason'] == 'planned_budget_outside_grant'
            assert {'set_budget', 'replace_creative', 'activate_campaign', 'activate_creative'} <= {a['action_type'] for a in plan['spec']['actions']}
            refused = post('merchant/plans/' + plan['plan_id'] + '/execute', {'expected_version': plan['version']})
            before_approval = get('ads')
            assert refused['status'] == 'WAIT_APPROVAL' and not refused['action_receipts']
            assert refused['authorization']['reason'] == 'planned_budget_outside_grant'
            assert before_approval['account'] == initial['account']
            assert before_approval['actions'] == initial['actions'], 'Mixed legal/out-of-grant plan must apply nothing'
            assert next(c for c in before_approval['campaigns'] if c['campaign_id'] == campaign['campaign_id'])['budget_cents'] == 0
            envelope = deepcopy(old_grant['envelope'])
            envelope.update(budget_cap_cents=cap,
                max_budget_change_cents=max(envelope['max_budget_change_cents'],
                    cap - sum(c['budget_cents'] for c in before_approval['campaigns'])))
            assert datetime.fromisoformat(envelope['valid_until'].replace('Z', '+00:00')) > datetime.now(timezone.utc) + timedelta(seconds=30)
            approved = post('ads/grants', {'grant_id': uuid.uuid4().hex, 'initial_plan_id': plan['plan_id'],
                'initial_plan_version': plan['version'], 'merchant_plan_id': plan['plan_id'],
                'replaces_grant_id': old_grant['grant_id'], 'envelope': envelope,
                'expected_campaign_versions': {c['campaign_id']: c['version'] for c in before_approval['campaigns']},
                'expected_creative_versions': {c['creative_id']: c['version'] for c in before_approval['creatives']}})
            paused = record('after_replacement_approval', get('ads'))
            assert paused['account']['spent_cents'] == 1 and paused['account']['account_id'] == initial['account']['account_id']
            assert next(c for c in paused['campaigns'] if c['campaign_id'] == prior['campaign_id'])['status'] == 'PAUSED'
            executed = post('merchant/plans/' + plan['plan_id'] + '/execute', {'expected_version': plan['version']})
            assert executed['status'] == 'WAIT_OBSERVATION' and executed['grant_id'] == approved['grant_id']
            assert executed['spec'] == plan['spec'], 'Approved immutable plan must not be rewritten'
            assert executed['action_receipts'] and all(r['receipt']['status'] == 'APPLIED' for r in executed['action_receipts'])
            changes = [c for r in executed['action_receipts'] for c in r['receipt']['changes']]
            assert len(changes) == len(plan['spec']['actions']) == 4
            assert {(c['action_type'], c['after'].get('creative_id') or c['after']['campaign_id']) for c in changes} == {
                (a['action_type'], a.get('creative_id') or a['campaign_id']) for a in plan['spec']['actions']}
            assert post('merchant/plans/' + plan['plan_id'] + '/execute', {'expected_version': plan['version']}) == executed
            after = get('ads')
            old_creative = next(c for c in after['creatives'] if c['creative_id'] == prior['creative_id'])
            assert old_creative['status'] == 'PAUSED', 'Replacement protection must not be silently resumed'
            assert old_creative['copy_text'] != initial['creatives'][0]['copy_text']
            assert next(c for c in after['campaigns'] if c['campaign_id'] == campaign['campaign_id'])['status'] == 'ACTIVE'
            user = java.request('admin', '/internal/demo/scenario/session', data={
                'executionScopeId': prior['execution_scope_id'], 'userIndex': 0, 'password': config['SMARTLECT_DEMO_PASSWORD']})
            with httpx.Client(base_url=base, timeout=25, trust_env=False) as visitor:
                visitor.cookies.set('token', user['token'])
                auth = visitor.get('/api/assistant/session').json()
                user_headers = {'Origin': base, 'X-CSRF-Token': auth['csrf_token']}
                request = {'exposure_id': uuid.uuid4().hex, 'creative_id': creative['creative_id']}
                record('new_exposure_request', request)
                response = visitor.post('/api/assistant/ads/exposures', json=request, headers=user_headers)
                assert response.status_code == 200
                exposure = record('new_exposure', response.json())
                request = {'exposure_id': exposure['exposure_id'], 'click_id': uuid.uuid4().hex}
                record('new_click_request', request)
                response = visitor.post('/api/assistant/ads/clicks', json=request, headers=user_headers)
                assert response.status_code == 200
                click = record('new_click', response.json())
                assert click['status'] == 'CHARGED' and click['amount_cents'] == 1
                assert visitor.post('/api/assistant/ads/clicks', json=request, headers=user_headers).json() == click
            final = record('final_ads', get('ads'))
            assert final['account']['spent_cents'] == 2 and final['account']['budget_cap_cents'] == cap
            assert final['account']['account_id'] == initial['account']['account_id']
            assert next(c for c in final['campaigns'] if c['campaign_id'] == prior['campaign_id'])['status'] == 'PAUSED'
            assert next(c for c in final['campaigns'] if c['campaign_id'] == campaign['campaign_id'])['budget_cents'] == cap - sum(c['budget_cents'] for c in initial['campaigns'])
            assert next(c for c in final['creatives'] if c['creative_id'] == creative['creative_id'])['status'] == 'ACTIVE'
            assert next(g for g in final['grants'] if g['grant_id'] == old_grant['grant_id'])['revoked_at']
            assert source.read_bytes() == raw
            evidence.update(status='PASSED', source_preserved=True, model_calls=0,
                checks=['mixed legal/out-of-grant plan applies nothing under existing grant',
                        'explicit replacement preserves cumulative spend and protective pause',
                        'original immutable plan executes and replays using approved transition',
                        'new draft campaign emits actual new exposure/click; same account grows from one to two cents'])
            save()
            return 0
    except Exception as error:
        evidence.update(status='FAILED', error_type=type(error).__name__,
            assertion=str(error) if isinstance(error, AssertionError) else None,
            failure_frames=[{'file': Path(f.filename).name, 'line': f.lineno} for f in traceback.extract_tb(error.__traceback__)])
        save()
        print('F5 reapproval failed; saved IDs and existing charges are retained.', flush=True)
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'artifacts/f5-live-merchant-v10.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/f5-reapproval.json')
    args = parser.parse_args()
    raise SystemExit(main(args.source, args.output))
