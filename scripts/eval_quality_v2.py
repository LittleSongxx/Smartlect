"""quality-v2 runner. Development only until holdout is frozen. No composite score."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
import traceback
import uuid

from quality_v2 import (ADS_PLAYBOOKS, CONTRACT_JSON, FREEZE_MANIFEST, HOLDOUT_DIR, SHOPPING_CATALOG, SHOPPING_DEV, SUPPORT_DEV,
                        AnnotationError, ads_grant_envelope, append_rerun_ledger, catalog_overlay_plan, digest,
                        live_support_cases, load_json, load_jsonl, observation_from_agent, provenance,
                        refuse_holdout, score_ads, score_shopping, score_support, self_check_scores,
                        validate_dev_sets, write_report)
from judge_quality_v2 import run_calibration, run_llm_judge, write_human_review
from runtime import ENV_FILE, ROOT, parse_env

ARTIFACT = ROOT / 'artifacts/quality-v2'


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def selected_cases(rows, wanted):
    if not wanted:
        return list(rows)
    keys = {item.strip() for chunk in wanted for item in chunk.split(',') if item.strip()}
    return [row for row in rows if row.get('case_id') in keys]


def growth_up():
    try:
        import httpx
        from runtime import ENV_FILE, parse_env
        port = parse_env(ENV_FILE)['SMARTLECT_GROWTH_PORT']
        with httpx.Client(timeout=2, trust_env=False) as client:
            return client.get('http://127.0.0.1:' + port + '/health').status_code == 200
    except Exception:
        return False


def collect_tools(client, agent_run_id):
    return client.rows('SELECT call_id,tool_name,arguments_json,outcome,receipt_json FROM tool_call '
                       'WHERE agent_run_id=%s ORDER BY started_at,call_id', (agent_run_id,))


def business_closeout_after_budget(record):
    """A completed rule-fallback closeout is a scored system outcome, not a channel fault.

    The model spent its own call budget; the controller then compiled a business
    closeout (legal empty / visible citations), possibly waiting on the user.
    Provider faults keep handoff_origin 'provider_fault' and stay setup_failed."""
    run = (record or {}).get('run') or {}
    result = run.get('result') or {}
    return (run.get('state') in {'COMPLETED', 'WAIT_USER'}
            and result.get('model_mode') == 'rule-fallback'
            and result.get('handoff_origin') != 'provider_fault')


def run_turns(client, texts):
    conversation = client.conversation()
    last = None
    tools = []
    for text in texts:
        try:
            last = client.message(conversation, text, label=text[:40])
        except AssertionError as error:
            if 'Run retains its actual requested model mode' not in str(error):
                raise
            record = client.evidence['model_runs'][-1]
            if not business_closeout_after_budget(record):
                raise
            last = (record.get('run') or {}).get('result')
        run_id = client.evidence['model_runs'][-1]['agent_run_id']
        tools.extend(collect_tools(client, run_id))
    result = (last or {})
    context = client.evidence['model_runs'][-1].get('run', {}).get('context') or {}
    failed = context.get('closeout') in {'provider_fault', 'budget_exceeded'} or result.get('handoff_origin') == 'provider_fault'
    return result, tools, failed


def commerce_mysql(config):
    import pymysql
    return pymysql.connect(host=config['SMARTLECT_MYSQL_HOST'], port=int(config['SMARTLECT_MYSQL_PORT']),
                           user=config['SMARTLECT_MYSQL_USER'], password=config['SMARTLECT_MYSQL_PASSWORD'],
                           database='smartlect_product', charset='utf8mb4',
                           cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                           connect_timeout=5, read_timeout=10, write_timeout=10)


def snapshot_overlay_priors(connection, plan):
    """Capture every row the overlay will touch so it can be restored afterwards."""
    priors = {'products': [], 'specs': [], 'skus': []}
    with connection.cursor() as cursor:
        for row in plan['products']:
            cursor.execute("SELECT product_name,product_desc,category_id,p_category_id,status,min_price,max_price "
                           "FROM product_info WHERE product_id=%s", (row['product_id'],))
            current = cursor.fetchone()
            if current is None:
                raise ValueError('overlay_product_missing:' + row['product_id'])
            priors['products'].append({'product_id': row['product_id'], **current})
            cursor.execute("SELECT property_value FROM product_property_value "
                           "WHERE product_id=%s AND property_value_id=%s",
                           (row['product_id'], row['primary_value_id']))
            spec = cursor.fetchone()
            if spec is None:
                raise ValueError('overlay_spec_missing:' + row['product_id'])
            priors['specs'].append({'product_id': row['product_id'], 'property_value_id': row['primary_value_id'],
                                    'property_value': spec['property_value']})
            cursor.execute("SELECT price FROM product_sku WHERE product_id=%s AND property_value_id_hash=%s",
                           (row['product_id'], row['primary_hash']))
            sku = cursor.fetchone()
            if sku is None:
                raise ValueError('overlay_sku_missing:' + row['gold_sku_key'])
            priors['skus'].append({'product_id': row['product_id'], 'property_value_id_hash': row['primary_hash'],
                                   'price': sku['price']})
    return priors


def restore_overlay(client, plan, priors, stock_priors, inserted_categories):
    """Reverse the overlay: products, specs, sku prices, stocks and freshly inserted categories."""
    def run(evidence):
        status = {'status': 'restored', 'error': None}
        try:
            config = parse_env(ENV_FILE)
            connection = commerce_mysql(config)
            try:
                with connection.cursor() as cursor:
                    for row in priors['products']:
                        cursor.execute("UPDATE product_info SET product_name=%s,product_desc=%s,category_id=%s,"
                                       "p_category_id=%s,status=%s,min_price=%s,max_price=%s WHERE product_id=%s",
                                       (row['product_name'], row['product_desc'], row['category_id'],
                                        row['p_category_id'], row['status'], row['min_price'], row['max_price'],
                                        row['product_id']))
                    for row in priors['specs']:
                        cursor.execute("UPDATE product_property_value SET property_value=%s "
                                       "WHERE product_id=%s AND property_value_id=%s",
                                       (row['property_value'], row['product_id'], row['property_value_id']))
                    for row in priors['skus']:
                        cursor.execute("UPDATE product_sku SET price=%s WHERE product_id=%s AND property_value_id_hash=%s",
                                       (row['price'], row['product_id'], row['property_value_id_hash']))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            for row, stock in zip(plan['products'], stock_priors['primary']):
                client.java.request('stock', '/internal/stock/set',
                                    data={'productId': row['product_id'], 'propertyValueIdHash': row['primary_hash'],
                                          'stock': stock})
            for row, stock in zip(plan['products'], stock_priors['extras']):
                for digest, value in stock:
                    client.java.request('stock', '/internal/stock/set',
                                        data={'productId': row['product_id'], 'propertyValueIdHash': digest,
                                              'stock': value})
            if inserted_categories:
                config = parse_env(ENV_FILE)
                connection = commerce_mysql(config)
                try:
                    with connection.cursor() as cursor:
                        for category in inserted_categories:
                            cursor.execute("DELETE FROM sys_category WHERE category_id=%s", (category,))
                    connection.commit()
                except Exception:
                    connection.rollback()
                finally:
                    connection.close()
        except Exception as error:  # restore is best effort but loudly recorded
            status = {'status': 'restore_failed', 'error': type(error).__name__ + ':' + str(error)[:200]}
        evidence.setdefault('catalog_overlay', {})['restore'] = status
        return status
    return run


def apply_shopping_catalog(client, evidence):
    catalog = load_json(SHOPPING_CATALOG)
    plan = catalog_overlay_plan(client.manifest, catalog)
    evidence['catalog_overlay'] = {'snapshot_id': catalog['snapshot_id'], 'plan': plan}
    config = parse_env(ENV_FILE)
    connection = commerce_mysql(config)
    priors = snapshot_overlay_priors(connection, plan)
    stock_priors = {'primary': [], 'extras': []}
    stock_query = ([{'productId': row['product_id'], 'propertyValueIdHash': row['primary_hash']}
                    for row in plan['products']]
                   + [{'productId': row['product_id'], 'propertyValueIdHash': digest}
                      for row in plan['products'] for digest in row['extra_hashes']])
    stock_rows = client.java.request('stock', '/internal/stock/getBatch', data=stock_query) if stock_query else []
    stock_map = {(row['productId'], row['propertyValueIdHash']): row.get('stock') for row in stock_rows}
    inserted_categories = []
    try:
        with connection.cursor() as cursor:
            for index, category in enumerate(plan['categories']):
                cursor.execute("INSERT INTO sys_category (category_id,category_name,p_category_id,sort) "
                               "VALUES (%s,%s,'0',%s) ON DUPLICATE KEY UPDATE category_id=category_id",
                               (category, category, 20 + index))
                if cursor.rowcount == 1:
                    inserted_categories.append(category)
            for row in plan['products']:
                price = Decimal(row['price_cents']).scaleb(-2)
                cursor.execute("UPDATE product_info SET product_name=%s,product_desc=%s,category_id=%s,"
                               "p_category_id='0',status=%s,min_price=%s,max_price=%s WHERE product_id=%s",
                               (row['productName'], row['productName'], row['live_category_id'],
                                row['status'], price, price, row['product_id']))
                if cursor.rowcount != 1:
                    raise ValueError('overlay_product_missing:' + row['product_id'])
                cursor.execute("UPDATE product_property_value SET property_value=%s "
                               "WHERE product_id=%s AND property_value_id=%s",
                               (row['specification'], row['product_id'], row['primary_value_id']))
                if cursor.rowcount != 1:
                    raise ValueError('overlay_spec_missing:' + row['product_id'])
                cursor.execute("UPDATE product_sku SET price=%s WHERE product_id=%s AND property_value_id_hash=%s",
                               (price, row['product_id'], row['primary_hash']))
                if cursor.rowcount != 1:
                    raise ValueError('overlay_sku_missing:' + row['gold_sku_key'])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    restore = restore_overlay(client, plan, priors, stock_priors, inserted_categories)
    for row in plan['products']:
        stock_priors['primary'].append(stock_map.get((row['product_id'], row['primary_hash']), 0))
        stock_priors['extras'].append([(digest, stock_map.get((row['product_id'], digest), 0))
                                       for digest in row['extra_hashes']])
    try:
        for row in plan['products']:
            client.java.request('stock', '/internal/stock/set',
                                data={'productId': row['product_id'], 'propertyValueIdHash': row['primary_hash'],
                                      'stock': row['stock']})
            for extra in row['extra_hashes']:
                client.java.request('stock', '/internal/stock/set',
                                    data={'productId': row['product_id'], 'propertyValueIdHash': extra, 'stock': 0})
        client.catalog = client.java.request('product', '/internal/product/snapshotBatch',
                                             data={'productIds': client.manifest['products']})
        products = {row['productId']: row for row in client.catalog.get('products', [])}
        skus = {(row['productId'], row['propertyValueIdHash']): row for row in client.catalog.get('skus', [])}
        values = {(row['productId'], row['propertyValueId']): row
                  for row in client.catalog.get('propertyValues', [])}
        mapped = {}
        for row in plan['products']:
            product = products.get(row['product_id'])
            sku = skus.get((row['product_id'], row['primary_hash']))
            spec = values.get((row['product_id'], row['primary_value_id']))
            if (not product or product.get('productName') != row['productName']
                    or product.get('status') != row['status']
                    or product.get('categoryId') != row['live_category_id']
                    or not sku or Decimal(str(sku.get('price'))) != Decimal(row['price_cents']).scaleb(-2)
                    or not spec or spec.get('propertyValue') != row['specification']):
                raise ValueError('overlay_snapshot_mismatch:' + row['gold_sku_key'])
            mapped[row['gold_sku_key']] = row['product_id'] + ':' + row['primary_hash']
    except Exception:
        restore(evidence)  # commit already landed; undo before propagating
        raise
    evidence['catalog_overlay']['live_sku_keys'] = mapped
    evidence['catalogue'] = client.catalog
    return restore


def run_shopping_live(output, wanted=None, split='development', trials=1):
    from scenario_client import ScenarioClient
    from quality_v2 import dataset_paths
    catalog = load_json(SHOPPING_CATALOG)
    rows = []
    for case in selected_cases(load_jsonl(dataset_paths(split)['shopping']), wanted):
        for trial in range(1, trials + 1):
            evidence = {'case_id': case['case_id'], 'line': 'shopping', 'status': 'SETUP_RUNNING',
                        'run_id': 'qv2-shop-' + uuid.uuid4().hex, 'scenario': 'quality-v2-shopping', 'seed': 42}
            if trials > 1:
                evidence['trial'] = trial
            path = output / 'shopping' / (case['case_id'] + ('.t%d' % trial if trials > 1 else '') + '.json')
            save = lambda: write(path, evidence)
            save()
            client = None
            try:
                client = ScenarioClient(evidence, save, requested_mode='live')
                client.setup(actor_ref='user_a', product_count=len(catalog['skus']))
                restore = apply_shopping_catalog(client, evidence)
                try:
                    result, tools, channel_failed = run_turns(client, case['user_turns'])
                    observation = observation_from_agent(result, tools, model_channel_failed=channel_failed,
                                                         gold_mode='snapshot',
                                                         setup_failed=channel_failed, setup_reason='provider_or_budget' if channel_failed else None)
                    evidence['observation'] = observation
                    evidence['scores'] = score_shopping(case, observation)
                    evidence['status'] = 'SCORED'
                finally:
                    restore(evidence)
            except AnnotationError:
                raise
            except Exception as error:
                evidence['status'] = 'SETUP_FAILED'
                evidence['error'] = type(error).__name__
                evidence['error_text'] = str(error)[:500]
                evidence['scores'] = score_shopping(case, {'setup_failed': True, 'setup_reason': type(error).__name__})
            finally:
                if client is not None:
                    client.close()
                if trials > 1 and evidence.get('scores') is not None:
                    evidence['scores']['trial'] = trial
                evidence['finished_at'] = now()
                save()
            rows.append(evidence['scores'])
    return rows


def run_support_live(output, wanted=None, split='development', trials=1):
    from eval_support import setup_knowledge
    from scenario_client import ScenarioClient
    from judge_quality_v2 import (apply_judge_answer_side, apply_judge_faithfulness,
                                  judge_config)
    from quality_v2 import dataset_paths
    cases = live_support_cases(load_jsonl(dataset_paths(split)['support']))
    rows = []
    judge_targets = []  # {'case','result','row','path'}: one entry per scored trial
    for case in selected_cases(cases, wanted):
        for trial in range(1, trials + 1):
            evidence = {'case_id': case['case_id'], 'line': 'support', 'status': 'SETUP_RUNNING',
                        'run_id': 'qv2-sup-' + uuid.uuid4().hex, 'scenario': 'quality-v2-support', 'seed': 42, 'documents': []}
            if trials > 1:
                evidence['trial'] = trial
            path = output / 'support' / (case['case_id'] + ('.t%d' % trial if trials > 1 else '') + '.json')
            save = lambda: write(path, evidence)
            save()
            client = None
            try:
                client = ScenarioClient(evidence, save, requested_mode='live')
                client.setup(actor_ref=case.get('actor') or 'user_a')
                setup = case.get('knowledge_setup') or {}
                rag_case = {'knowledge_setup': {'additional_documents': []}}
                for doc_id in case.get('visible_doc_ids') or []:
                    body = (ROOT / 'fixtures/knowledge' / (doc_id + '.md')).read_text()
                    rag_case['knowledge_setup']['additional_documents'].append({
                        'doc_id': doc_id, 'version': 1, 'title': body.splitlines()[0].lstrip('# '),
                        'source_uri': 'fixtures/knowledge/' + doc_id + '.md', 'body': body, 'acl': 'PUBLIC',
                        'lifecycle': 'publish_before_question',
                        'checksum_sha256': __import__('hashlib').sha256(body.encode()).hexdigest()})
                for extra in setup.get('additional_documents') or []:
                    rag_case['knowledge_setup']['additional_documents'].append(extra)
                for extra in setup.get('documents') or []:
                    body = (ROOT / extra['source_uri']).read_text()
                    rag_case['knowledge_setup']['additional_documents'].append({
                        **extra, 'body': extra.get('body') or body,
                        'title': extra.get('title') or body.splitlines()[0].lstrip('# '),
                        'acl': extra.get('acl') or 'PUBLIC',
                        'checksum_sha256': extra.get('checksum_sha256') or __import__('hashlib').sha256(body.encode()).hexdigest()})
                empty_manifest = {'base_corpus': {'documents': []}}
                setup_knowledge(client, evidence, save, empty_manifest, rag_case)
                result, tools, channel_failed = run_turns(client, case['user_turns'])
                ticket = result.get('ticket')
                observation = {'result': result, 'tool_calls': [{'tool_name': row['tool_name'],
                               'arguments_json': row.get('arguments_json'), 'receipt_json': row.get('receipt_json')}
                              for row in tools], 'ticket': ticket,
                               'setup_failed': channel_failed, 'model_channel_failed': channel_failed}
                evidence['observation'] = observation
                evidence['scores'] = score_support(case, observation)
                evidence['status'] = 'SCORED'
                if not channel_failed and case.get('checkable_claims'):
                    judge_targets.append({'case': case, 'result': result, 'row': evidence['scores'],
                                          'path': path})
            except AnnotationError:
                raise
            except Exception as error:
                evidence['status'] = 'SETUP_FAILED'
                evidence['error'] = type(error).__name__
                evidence['error_text'] = str(error)[:800]
                evidence['scores'] = score_support(case, {'setup_failed': True})
            finally:
                if client is not None:
                    client.close()
                if trials > 1 and evidence.get('scores') is not None:
                    evidence['scores']['trial'] = trial
                evidence['finished_at'] = now()
                save()
            rows.append(evidence['scores'])
    if judge_targets:
        errors = []
        pairs = [(target['case'], target['result'], target['row']) for target in judge_targets]
        apply_judge_faithfulness(rows, pairs, judge_config(), errors=errors)
        apply_judge_answer_side(rows, pairs, judge_config(), errors=errors)
        for target in judge_targets:
            if not target['path'].exists():
                continue
            evidence = json.loads(target['path'].read_text())
            evidence['scores'] = target['row']
            if errors:
                evidence['judge_errors'] = [item for item in errors if item['case_id'] == target['case']['case_id']]
            write(target['path'], evidence)
        if errors:
            print('judge_errors:', json.dumps(errors, ensure_ascii=False))
        sampled = write_human_review(output, judge_targets)
        if sampled:
            print('judge_human_review_sampled:', sampled)
    return rows


def campaign_metrics_from_growth(client, campaign_id):
    scope = client.scope
    impressions = client.rows(
        "SELECT exposure_id FROM ad_interaction WHERE execution_scope_id=%s "
        "AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.campaign_id'))=%s",
        (scope, campaign_id))
    clicks = client.rows(
        "SELECT click_id FROM ad_spend WHERE execution_scope_id=%s AND campaign_id=%s",
        (scope, campaign_id))
    attributed = client.rows(
        "SELECT e.pay_order_id FROM commerce_event e "
        "LEFT JOIN commerce_attribution a USING(event_id) "
        "LEFT JOIN commerce_attribution_meta m USING(event_id) "
        "WHERE e.status='APPLIED' AND e.event_type='PAYMENT' "
        "AND COALESCE(a.execution_scope_id,m.execution_scope_id,'store')=%s "
        "AND a.campaign_id=%s",
        (scope, campaign_id))
    unknown = client.rows(
        "SELECT e.pay_order_id FROM commerce_event e "
        "LEFT JOIN commerce_attribution a USING(event_id) "
        "LEFT JOIN commerce_attribution_meta m USING(event_id) "
        "WHERE e.status='APPLIED' AND e.event_type='PAYMENT' "
        "AND COALESCE(a.execution_scope_id,m.execution_scope_id,'store')=%s "
        "AND (a.campaign_id IS NULL OR a.campaign_id='')",
        (scope,))
    return {
        'impressions': len(impressions),
        'clicks': len(clicks),
        'payment_conversions': len({row['pay_order_id'] for row in attributed if row.get('pay_order_id')}),
        'unknown_payments': len({row['pay_order_id'] for row in unknown if row.get('pay_order_id')}),
    }


def pick_live_sku(client, exclude_key=None):
    snapshot = client.catalog
    stocks = { (row['productId'], row['propertyValueIdHash']): row.get('stock')
               for row in client.java.request('stock', '/internal/stock/getBatch', data=[
                   {'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}
                   for sku in snapshot.get('skus', [])]) } if snapshot.get('skus') else {}
    for sku in snapshot.get('skus', []):
        product = next((row for row in snapshot.get('products', []) if row['productId'] == sku['productId']), None)
        key = sku['productId'] + ':' + sku['propertyValueIdHash']
        if (exclude_key is None or key != exclude_key) and product and product.get('status') == 1 \
                and stocks.get((sku['productId'], sku['propertyValueIdHash']), 0) >= 1:
            return {**sku, 'product_name': product.get('productName')}
    raise ValueError('no_sellable_sku_in_scenario')


def wait_attribution_settled(client, pay_id, timeout=45):
    """Poll until the payment's attribution row is FINAL; return its campaign_id (or None)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        report = client.request('attribution', params={'payOrderId': pay_id}, merchant=True)
        events = report.get('events') or []
        payment = next((row for row in events if row.get('event_type') == 'PAYMENT'), None)
        if payment and payment.get('calculation_status') == 'FINAL':
            return payment.get('campaign_id') or None
        time.sleep(.3)
    raise AssertionError('attribution_not_settled:' + pay_id)


def pay_sku(client, sku):
    conversation = client.conversation()
    proposal = client.propose(conversation, 'order', {
        'payMethod': 'mock', 'addressId': client.session['addressId'], 'orderFrom': 0,
        'orderList': [{'productId': sku['productId'],
                       'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]})
    confirmed = client.confirm(proposal)
    paid = client.pay(confirmed)
    pay_id = (paid.get('payOrderId') or (confirmed.get('receipt') or {}).get('payOrderId'))
    if not pay_id:
        raise ValueError('confirm_missing_pay_order')
    return pay_id


def _ads_second_user_session(client):
    """A user_b session inside the existing scenario (for viewer-isolation probes)."""
    session = client.java.request('admin', '/internal/demo/scenario/session', data={
        'executionScopeId': client.scope, 'userIndex': 1,
        'password': client.config['SMARTLECT_DEMO_PASSWORD']})
    import httpx
    probe = httpx.Client(base_url=client.base, timeout=35, trust_env=False)
    probe.cookies.set('token', session['token'])
    auth = probe.get('/api/assistant/session')
    auth.raise_for_status()
    auth = auth.json()
    return probe, {'Origin': client.base, 'X-CSRF-Token': auth['csrf_token']}


def _ads_probe_rank(client, layout, step):
    target, headers = client.user, client.uheaders
    guest = None
    if step.get('as_actor') == 'user_b':
        guest = _ads_second_user_session(client)
        target, headers = guest
    try:
        response = target.get('/api/assistant/ads/recommendations',
                              params={'limit': 4}, headers=headers)
        response.raise_for_status()
        items = response.json().get('items') or []
    finally:
        if guest is not None:
            guest[0].close()
    by_creative = {row['creative_id']: slot for slot, row in layout['creative_slots'].items()}
    observed_first = next((by_creative[row.get('creative_id')] for row in items
                           if row.get('creative_id') in by_creative), None)
    return {'expect_first': step.get('expect_first'), 'observed_first': observed_first,
            'observed_items': len(items), 'as_actor': step.get('as_actor')}


def _ads_expect_reject(client, layout, step, exposures_by_slot):
    row = layout['creative_slots'][step['slot']]
    if step['http'] == 'click':
        exposure = exposures_by_slot[step['slot']].pop(0)
        payload, path = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}, 'ads/clicks'
    else:
        payload, path = {'exposure_id': uuid.uuid4().hex, 'creative_id': row['creative_id']}, 'ads/exposures'
    result = client.request(path, payload, accepted=(200, 409))
    status = result.get('http_status', 200) if isinstance(result, dict) else 200
    error_text = json.dumps(result.get('body'), ensure_ascii=False) if status != 200 else ''
    return {'op': step['http'], 'slot': step['slot'], 'expected_error': step['error'],
            'observed_status': status, 'observed_error': error_text}


def _run_scripted_book(client, book, ad_sku):
    """Fatigue/pacing/budget playbooks: slot-prefixed ids keep rank ties breaking
    in the scripted direction while a per-run hash keeps them globally unique
    (campaign_id is a global primary key, so fixed ids would collide across runs);
    every scripted expectation becomes one assertion."""
    import hashlib
    tag = hashlib.sha256(client.evidence['run_id'].encode()).hexdigest()
    layout = {'creative_slots': {}, 'campaign_ids': []}
    for spec in book['campaigns']:
        slot = spec['slot']
        campaign_id = slot[0] + tag[:31]
        layout['campaign_ids'].append(campaign_id)
        client.request('ads/campaigns', {'campaign_id': campaign_id,
            'name': 'quality-v2 %s %s' % (book['playbook_id'], slot),
            'product_id': ad_sku['productId'], 'sku_key': ad_sku['propertyValueIdHash'],
            'budget_cents': spec['budget_cents'], 'cpc_cents': spec['cpc_cents']}, merchant=True)
        for creative in spec.get('creatives') or [slot]:
            creative_id = ('c' + creative + tag)[:32]
            client.request('ads/creatives', {'creative_id': creative_id, 'campaign_id': campaign_id,
                'copy_text': '模拟推广质量评测'}, merchant=True)
            layout['creative_slots'][creative] = {'campaign_id': campaign_id, 'creative_id': creative_id}
    snapshot = client.request('ads', merchant=True)
    grant = client.request('ads/grants', {
        'grant_id': uuid.uuid4().hex, 'initial_plan_id': uuid.uuid4().hex, 'initial_plan_version': 1,
        'expected_campaign_versions': {row['campaign_id']: row['version'] for row in snapshot['campaigns']},
        'expected_creative_versions': {row['creative_id']: row['version'] for row in snapshot.get('creatives', [])},
        'envelope': ads_grant_envelope([ad_sku['productId']])}, merchant=True)
    snapshot = client.request('ads', merchant=True)
    grant_id = grant.get('grant_id') or (snapshot.get('account') or {}).get('grant_id')
    if not grant_id:
        raise ValueError('grant_id_missing')
    for kind, key, id_field, version_of in (
            ('activate_campaign', 'campaigns', 'campaign_id', 'campaign_id'),
            ('activate_creative', 'creatives', 'creative_id', 'creative_id')):
        for row in snapshot[key]:
            key_id = uuid.uuid4().hex
            action = {'action_id': key_id, 'idempotency_key': key_id, 'grant_id': grant_id,
                      'plan_id': key_id, 'plan_version': 1, 'reason_code': 'quality_v2_activate',
                      'evidence_ids': [], 'actions': [
                          {'action_type': kind, id_field: row[id_field], 'expected_version': row['version']}]}
            if kind == 'activate_creative':
                action['actions'][0]['campaign_id'] = row['campaign_id']
            client.request('ads/actions', action, merchant=True)
    exposures_by_slot = {slot: [] for slot in layout['creative_slots']}
    probes, rejections, status_probes = [], [], []
    campaign_of_slot = {spec['slot']: slot[0] + tag[:31] for spec in book['campaigns']}
    for step in book['script']:
        op = step['op']
        if op == 'expose':
            row = layout['creative_slots'][step['slot']]
            for _ in range(step['count']):
                exposure = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex,
                    'creative_id': row['creative_id']})
                exposures_by_slot[step['slot']].append(exposure)
        elif op == 'click':
            for _ in range(step['count']):
                exposure = exposures_by_slot[step['slot']].pop(0)
                client.request('ads/clicks', {'click_id': uuid.uuid4().hex,
                    'exposure_id': exposure['exposure_id']})
        elif op == 'probe_rank':
            probes.append(_ads_probe_rank(client, layout, step))
        elif op == 'probe_status':
            snapshot = client.request('ads', merchant=True)
            campaign_id = campaign_of_slot[step['slot']]
            row = next(item for item in snapshot['campaigns'] if item['campaign_id'] == campaign_id)
            status_probes.append({'slot': step['slot'], 'observed_status': row.get('status'),
                                  'observed_pause_reason': row.get('pause_reason')})
        elif op == 'reject':
            rejections.append(_ads_expect_reject(client, layout, step, exposures_by_slot))
    totals = {key: 0 for key in ('impressions', 'clicks', 'payment_conversions')}
    for campaign_id in layout['campaign_ids']:
        metrics = campaign_metrics_from_growth(client, campaign_id)
        for key in totals:
            totals[key] += metrics.get(key) or 0
    totals['unknown_payments'] = 0
    return {'campaign_metrics': totals, 'used_summary_payment_conversions': False,
            'used_recommendation_clicks': False, 'rank_probes': probes,
            'rejections': rejections, 'status_probes': status_probes, 'ads_layout': layout}


def run_ads_live(output, split='development'):
    from scenario_client import ScenarioClient
    from quality_v2 import dataset_paths
    playbooks = load_json(dataset_paths(split)['ads'])['playbooks']
    rows = []
    for book in playbooks:
        evidence = {'playbook_id': book['playbook_id'], 'line': 'ads', 'status': 'SETUP_RUNNING',
                    'run_id': 'qv2-ads-' + uuid.uuid4().hex, 'scenario': 'quality-v2-ads', 'seed': 42}
        path = output / 'ads' / (book['playbook_id'] + '.json')
        save = lambda: write(path, evidence)
        save()
        client = None
        try:
            client = ScenarioClient(evidence, save, requested_mode='configured')
            client.setup(actor_ref='user_a')
            if 'script' in book:
                observation = _run_scripted_book(client, book, pick_live_sku(client))
                metrics = observation['campaign_metrics']
                evidence['observation'] = observation
            else:
                ad_sku = None if book['kind'] == 'organic_payment' else pick_live_sku(client)
                buy_sku = None
                if book['traffic']['payments']:
                    buy_sku = pick_live_sku(client, exclude_key=(
                        ad_sku['productId'] + ':' + ad_sku['propertyValueIdHash']
                        if book.get('buy') == 'other_sku' and ad_sku else None))
                campaign_id = creative_id = None
                if ad_sku is not None:
                    campaign_id, creative_id = uuid.uuid4().hex, uuid.uuid4().hex
                    client.request('ads/campaigns', {'campaign_id': campaign_id, 'name': 'quality-v2 ' + book['playbook_id'],
                        'product_id': ad_sku['productId'], 'sku_key': ad_sku['propertyValueIdHash'],
                        'budget_cents': 2000, 'cpc_cents': 10}, merchant=True)
                    client.request('ads/creatives', {'creative_id': creative_id, 'campaign_id': campaign_id,
                        'copy_text': '模拟推广质量评测'}, merchant=True)
                    snapshot = client.request('ads', merchant=True)
                    grant = client.request('ads/grants', {
                        'grant_id': uuid.uuid4().hex, 'initial_plan_id': uuid.uuid4().hex, 'initial_plan_version': 1,
                        'expected_campaign_versions': {row['campaign_id']: row['version'] for row in snapshot['campaigns']},
                        'expected_creative_versions': {row['creative_id']: row['version'] for row in snapshot.get('creatives', [])},
                        'envelope': ads_grant_envelope([ad_sku['productId']])}, merchant=True)
                    snapshot = client.request('ads', merchant=True)
                    grant_id = grant.get('grant_id') or (snapshot.get('account') or {}).get('grant_id')
                    if not grant_id:
                        raise ValueError('grant_id_missing')
                    campaign_version = next(row['version'] for row in snapshot['campaigns'] if row['campaign_id'] == campaign_id)
                    key = uuid.uuid4().hex
                    client.request('ads/actions', {
                        'action_id': key, 'idempotency_key': key, 'grant_id': grant_id,
                        'plan_id': key, 'plan_version': 1, 'reason_code': 'quality_v2_activate',
                        'evidence_ids': [], 'actions': [
                            {'action_type': 'activate_campaign', 'campaign_id': campaign_id,
                             'expected_version': campaign_version}]}, merchant=True)
                    snapshot = client.request('ads', merchant=True)
                    creative_version = next(row['version'] for row in snapshot['creatives'] if row['creative_id'] == creative_id)
                    key = uuid.uuid4().hex
                    client.request('ads/actions', {
                        'action_id': key, 'idempotency_key': key, 'grant_id': grant_id,
                        'plan_id': key, 'plan_version': 1, 'reason_code': 'quality_v2_activate',
                        'evidence_ids': [], 'actions': [
                            {'action_type': 'activate_creative', 'campaign_id': campaign_id,
                             'creative_id': creative_id, 'expected_version': creative_version}]}, merchant=True)
                traffic = book['traffic']
                exposures = []
                if ad_sku is not None:
                    recs = client.request('ads/recommendations', params={'limit': 2})
                    creative = next((row for row in recs.get('items') or recs.get('recommendations') or []
                                     if row.get('campaign_id') == campaign_id or row.get('creative_id') == creative_id), None)
                    if creative is None and (recs.get('items') or recs.get('recommendations')):
                        creative = (recs.get('items') or recs.get('recommendations'))[0]
                    if creative is None:
                        raise ValueError('no_ad_candidate')
                    for _ in range(traffic['impressions']):
                        exposure = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex,
                            'creative_id': creative.get('creative_id') or creative_id})
                        exposures.append(exposure)
                    for index in range(traffic['clicks']):
                        client.request('ads/clicks', {'click_id': uuid.uuid4().hex,
                            'exposure_id': exposures[index]['exposure_id']})
                if traffic['payments']:
                    pay_id = pay_sku(client, buy_sku)
                    attributed_campaign = wait_attribution_settled(client, pay_id)
                    evidence['payment_attribution_campaign_id'] = attributed_campaign
                metrics = campaign_metrics_from_growth(client, campaign_id) if campaign_id else {
                    'impressions': 0, 'clicks': 0, 'payment_conversions': 0,
                    'unknown_payments': len(client.rows(
                        "SELECT DISTINCT e.pay_order_id FROM commerce_event e "
                        "LEFT JOIN commerce_attribution a USING(event_id) "
                        "LEFT JOIN commerce_attribution_meta m USING(event_id) "
                        "WHERE e.status='APPLIED' AND e.event_type='PAYMENT' "
                        "AND COALESCE(a.execution_scope_id,m.execution_scope_id,'store')=%s "
                        "AND (a.campaign_id IS NULL OR a.campaign_id='')", (client.scope,)))}
                observation = {'campaign_metrics': metrics,
                               'used_summary_payment_conversions': False, 'used_recommendation_clicks': False}
                evidence['observation'] = observation
            scored = score_ads(book, observation)
            evidence['campaign_metrics'] = metrics
            evidence['scores'] = scored
            evidence['status'] = 'SCORED'
        except AnnotationError:
            raise
        except Exception as error:
            evidence['status'] = 'SETUP_FAILED'
            evidence['error'] = type(error).__name__
            evidence['error_text'] = str(error)[:800]
            evidence['failure_frames'] = [{'file': Path(frame.filename).name, 'line': frame.lineno}
                                          for frame in traceback.extract_tb(error.__traceback__)]
            evidence['scores'] = score_ads(book, {'setup_failed': True})
        finally:
            if client is not None:
                client.close()
            evidence['finished_at'] = now()
            save()
        rows.append(evidence['scores'])
    return rows


def print_lines(report):
    print(json.dumps({
        'official': report['official'],
        'partial': report.get('partial'),
        'synthetic': report.get('synthetic'),
        'composite_score': report['composite_score'],
        'note': report['note'],
        'shopping': report['shopping'],
        'support': report['support'],
        'ads': report['ads'],
        'rerun_ledger': report.get('rerun_ledger'),
        'provenance': report['provenance'],
    }, ensure_ascii=False, indent=2))


def freeze_holdout():
    """Stamp dev-set digests. Authoring the holdout questions stays a human task."""
    if FREEZE_MANIFEST.exists():
        raise SystemExit('holdout_already_frozen:' + str(FREEZE_MANIFEST))
    manifest = {
        'schema_version': 'quality-v2-holdout-freeze-v1',
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'frozen_by': 'scripts/eval_quality_v2.py freeze',
        'note': '冻结开发集形态。留出题目尚未出；出题后以其自身 manifest 为准，禁止用留出调系统。',
        'dev_digests': {
            'shopping_dev_sha256': digest(SHOPPING_DEV),
            'support_dev_sha256': digest(SUPPORT_DEV),
            'ads_playbooks_sha256': digest(ADS_PLAYBOOKS),
            'catalog_snapshot_sha256': digest(SHOPPING_CATALOG),
            'metrics_contract_sha256': digest(CONTRACT_JSON),
        },
        'provenance': provenance(),
    }
    HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
    FREEZE_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='quality-v2 development evaluation')
    parser.add_argument('command', choices=('self-check', 'validate', 'freeze', 'judge',
                                            'judge-calibrate', 'run', 'report', 'score'))
    parser.add_argument('--line', choices=('shopping', 'support', 'ads', 'all'), default='all')
    parser.add_argument('--split', default='development')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--output', default=None)
    parser.add_argument('--official', action='store_true')
    parser.add_argument('--trials', type=int, default=1,
                        help='每题独立试验次数（各自 fresh scenario；导购/客服适用，ads 为确定性模拟只跑单次）')
    parser.add_argument('--sample', type=int, default=None,
                        help='judge: sample N cases per line; default judges every claim case (dev only)')
    parser.add_argument('--pro-model', default='deepseek-v4-pro',
                        help='judge-calibrate: second judge model for cross-judging')
    parser.add_argument('--case', action='append', default=[],
                        help='optional case_id; repeat or comma-separate to rerun a subset')
    args = parser.parse_args()
    if args.trials < 1:
        raise SystemExit('--trials must be >= 1')
    refuse_holdout(args.split)
    if args.split == 'holdout':
        from quality_v2 import holdout_ready
        holdout_ready(() if args.line == 'all' else (args.line,))
    run_id = args.run_id or (args.command + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output = Path(args.output) if args.output else ARTIFACT / run_id
    lines = ('shopping', 'support', 'ads') if args.line == 'all' else (args.line,)

    if args.command == 'self-check':
        shopping, support, ads = self_check_scores()
        report = write_report(output, shopping, support, ads, official=False, synthetic=True)
        print_lines(report)
        return
    if args.command == 'validate':
        validate_dev_sets(lines, split=args.split)
        print(f'{args.split}_sets_ok:', ','.join(lines))
        return
    if args.command == 'freeze':
        freeze_holdout()
        return
    if args.command == 'judge':
        run_llm_judge(output, lines, sample=args.sample)
        return
    if args.command == 'judge-calibrate':
        run_calibration(output, pro_model=args.pro_model)
        return
    if args.command == 'report':
        summary = load_json(output / 'summary.json') if (output / 'summary.json').exists() else None
        if summary is None:
            raise SystemExit('missing_summary; run self-check or run first')
        print_lines(summary)
        return
    if args.command == 'run':
        if not growth_up():
            raise SystemExit('growth_not_healthy; use self-check or start an isolated stack')
        validate_dev_sets(lines, split=args.split)
        shopping, support, ads = [], [], []
        if 'shopping' in lines:
            shopping = run_shopping_live(output, args.case, split=args.split, trials=args.trials)
        if 'support' in lines:
            support = run_support_live(output, args.case, split=args.split, trials=args.trials)
        if 'ads' in lines:
            ads = run_ads_live(output, split=args.split)
        report = write_report(output, shopping, support, ads,
                              official=args.official, partial=bool(args.case), trials=args.trials)
        append_rerun_ledger(output, report)
        print_lines(report)
        return
    raise SystemExit('unknown_command')


if __name__ == '__main__':
    main()
