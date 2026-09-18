"""Shared helpers for the quality-v2 eval pipeline and demo seeding.

Extracted from the retired f-series/rag drivers (check_f3/check_f4/demo/eval_rag)
during the 2026-09-12 cleanup so the current pipeline no longer depends on
deleted files. Behaviour is unchanged; sources live in git history.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
import re
import subprocess
import time
from urllib.parse import quote

from runtime import ROOT


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value.replace(tzinfo=timezone.utc)


def json_value(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError('unsupported evidence value')


def proposal_from(result):
    return result.get('proposal') or result['result']['proposal']


def login_merchant(client, config):
    challenge = client.post('/admin-api/account/checkCode')
    challenge.raise_for_status()
    challenge = challenge.json()
    assert challenge['code'] == 200, 'Java CAPTCHA request failed'
    key = challenge['data']['checkCodeKey']
    # Only the one newly requested local CAPTCHA is read; no credential appears in argv or evidence.
    env = {**os.environ, 'REDISCLI_AUTH': config['SMARTLECT_REDIS_PASSWORD']}
    response = subprocess.run(['docker', 'exec', '-e', 'REDISCLI_AUTH', 'smartlect-redis-1',
        'redis-cli', '--raw', 'GET', 'smartlect:checkcode:' + key],
        env=env, capture_output=True, text=True, timeout=10)
    assert response.returncode == 0, 'Local CAPTCHA lookup failed'
    captcha = json.loads(response.stdout)
    assert isinstance(captcha, str) and captcha.isdigit(), 'Local CAPTCHA value unavailable'
    result = client.post('/admin-api/account/login', data={
        'account': config.get('SMARTLECT_ADMIN_ACCOUNT', 'admin'),
        'password': config['SMARTLECT_ADMIN_PASSWORD'], 'checkCode': captcha, 'checkCodeKey': key})
    assert result.status_code == 200 and result.json()['code'] == 200, 'Java merchant login failed'
    auth = client.get('/admin-api/assistant/session')
    assert auth.status_code == 200, 'Merchant session bridge failed'
    auth = auth.json()
    assert auth['actor']['subject_type'] == 'merchant' and 'admin:legacy' in auth['actor']['permissions']
    return {'Origin': str(client.base_url).rstrip('/'), 'X-CSRF-Token': auth['csrf_token']}


def cents(value):
    from smartlect.money import to_cents
    return to_cents(str(value))


def wait_for(read, predicate, label, timeout=40):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out waiting for {label}: {value}")
        time.sleep(0.2)


def api(client, evidence, save, path, payload=None, *, merchant=False, method=None, params=None):
    if re.search(r'(?:confirm|payments|proposals|ads)(?:/|$)', path):
        raise ValueError('rag_runner_cannot_authorize_or_execute_transactions')
    record = {'path': path, 'merchant': merchant, 'method': method or ('POST' if payload is not None else 'GET'),
              'request': payload, 'params': params, 'started_at': now()}
    evidence.setdefault('api', []).append(record)
    save()
    result = client.request(path, payload, merchant=merchant, method=method, params=params,
                            accepted=tuple(range(100, 600)))
    record.update(response=result, completed_at=now())
    save()
    if isinstance(result, dict) and 'http_status' in result:
        raise ValueError('rag_api_http_' + str(result['http_status']))
    return result


def server_time(client):
    # Read-only Growth DB clock matches knowledge lifecycle filtering; never adjust DB time.
    return client.rows('SELECT UTC_TIMESTAMP(6) AS now')[0]['now'].replace(tzinfo=timezone.utc)


def source_documents(manifest, case):
    documents = []
    for source in manifest['base_corpus']['documents']:
        body = (ROOT / source['source_uri']).read_text()
        documents.append({**source, 'body': body, 'title': body.splitlines()[0].lstrip('# '),
            'acl': 'PUBLIC', 'lifecycle': 'publish_before_question', 'checksum_sha256': source['sha256']})
    documents.extend(case.get('knowledge_setup', {}).get('additional_documents', []))
    resolved = []
    for source in documents:
        # Extra docs may reference their body by source_uri instead of inlining it.
        if not source.get('body') and source.get('source_uri'):
            source = {**source, 'body': (ROOT / source['source_uri']).read_text()}
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', source['doc_id']) or sha256(source['body'].encode()).hexdigest() != source['checksum_sha256']:
            raise ValueError('fixture_document_identity_or_checksum_mismatch')
        resolved.append(source)
    return resolved


def setup_knowledge(client, evidence, save, manifest, case):
    documents = evidence['documents'] = []
    actor_ids = {name: client.manifest['users'][index]['userId'] for name, index in [('user_a', 0), ('user_b', 1)]}
    for source in source_documents(manifest, case):
        current = server_time(client)
        lifecycle = source.get('lifecycle', 'publish_before_question')
        if lifecycle not in {'publish_before_question', 'publish_then_wait_for_expiry', 'publish_then_withdraw_before_question',
                             'draft_only', 'publish_with_future_valid_from'}:
            raise ValueError('unsupported_document_lifecycle')
        start, end = current - timedelta(days=1), current + timedelta(days=30)
        if lifecycle == 'publish_then_wait_for_expiry':
            duration = source['valid_for_seconds']
            if type(duration) is not int or not 1 <= duration <= 300:
                raise ValueError('invalid_expiry_wait')
            end = current + timedelta(seconds=duration)
        if lifecycle == 'publish_with_future_valid_from':
            start = current + timedelta(seconds=source['valid_from_offset_seconds'])
            end = start + timedelta(days=30)
        request = {k: source[k] for k in ('doc_id', 'title', 'body', 'acl', 'source_uri')}
        request.update(facts=source.get('facts', {}), valid_from=start.isoformat(), valid_until=end.isoformat())
        if source.get('acl_actor_ref'):
            request['acl_actor_id'] = actor_ids[source['acl_actor_ref']]
        created = api(client, evidence, save, 'knowledge', request, merchant=True)
        if created['version'] != source['version'] or created['checksum'] != source['checksum_sha256']:
            raise ValueError('published_fixture_version_or_checksum_changed')
        documents.append(created)
        save()
        path = f"knowledge/{quote(source['doc_id'], safe='')}/{created['version']}"
        if lifecycle != 'draft_only':
            published = api(client, evidence, save, path + '/publish', {}, merchant=True)
            if published['status'] != 'PUBLISHED' or server_time(client) >= end:
                raise ValueError('document_did_not_publish_while_valid')
        if lifecycle == 'publish_then_withdraw_before_question':
            withdrawn = api(client, evidence, save, path + '/withdraw', {}, merchant=True)
            if withdrawn['status'] != 'WITHDRAWN':
                raise ValueError('withdrawal_not_verified')
        if lifecycle == 'publish_then_wait_for_expiry':
            deadline = time.monotonic() + 310
            while server_time(client) < end:
                if time.monotonic() >= deadline:
                    raise ValueError('expiry_not_verified')
                time.sleep(.3)
        checked = api(client, evidence, save, path, merchant=True)
        checked['setup_lifecycle'] = lifecycle
        checked['setup_verified_at'] = server_time(client).isoformat()
        if lifecycle == 'publish_with_future_valid_from' and timestamp(checked['setup_verified_at']) >= start:
            raise ValueError('future_policy_became_current_before_question')
        documents[-1] = checked
        save()
    return evidence
