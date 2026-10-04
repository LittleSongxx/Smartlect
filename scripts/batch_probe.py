"""小批回归夹具：评测-修复循环专用（非官方 run，不进台账）。

用法：assistant/.venv/bin/python batch_probe.py shop-d-02 shop-d-04 ... [--line support]
每题 1 次试验，逐题打印 outcome/关键分，失败题打印签名。
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, '.')
from quality_v2 import load_jsonl, SHOPPING_DEV, SUPPORT_DEV, score_shopping, score_support
import eval_quality_v2 as eq
from scenario_client import ScenarioClient


def run_cases(line, case_ids):
    cases = [c for c in load_jsonl(SHOPPING_DEV if line == 'shopping' else SUPPORT_DEV)
             if c['case_id'] in case_ids]
    results = []
    for case in cases:
        import uuid as _uuid
        ev = {'run_id': 'qv2-probe-' + _uuid.uuid4().hex, 'scenario':
              'quality-v2-support' if line == 'support' else 'quality-v2-shopping', 'seed': 42}
        def save(*a, **k):
            return None
        client = None
        try:
            client = ScenarioClient(ev, save, requested_mode='live')
            if line == 'shopping':
                from quality_v2 import SHOPPING_CATALOG
                catalog = load_json(SHOPPING_CATALOG) if False else None
                from quality_v2 import load_json, SHOPPING_CATALOG as SC
                catalog = load_json(SC)
                client.setup(actor_ref='user_a', product_count=len(catalog['skus']))
                restore = eq.apply_shopping_catalog(client, ev)
                try:
                    result, tools, failed = eq.run_turns(client, case['user_turns'])
                    obs = eq.observation_from_agent(result, tools, model_channel_failed=failed,
                                                    gold_mode='snapshot', setup_failed=failed)
                    scores = score_shopping(case, obs)
                finally:
                    try:
                        restore(evidence=ev)
                    except Exception:
                        pass
            else:
                from eval_support import setup_knowledge
                from runtime import ROOT as REPO_ROOT
                setup_extra = case.get('knowledge_setup') or {}
                rag_case = {'knowledge_setup': {'additional_documents': []}}
                for doc_id in case.get('visible_doc_ids') or []:
                    body = (REPO_ROOT / 'fixtures/knowledge' / (doc_id + '.md')).read_text()
                    rag_case['knowledge_setup']['additional_documents'].append({
                        'doc_id': doc_id, 'version': 1, 'title': body.splitlines()[0].lstrip('# '),
                        'source_uri': 'fixtures/knowledge/' + doc_id + '.md', 'body': body, 'acl': 'PUBLIC',
                        'lifecycle': 'publish_before_question',
                        'checksum_sha256': __import__('hashlib').sha256(body.encode()).hexdigest()})
                for extra in setup_extra.get('additional_documents') or []:
                    rag_case['knowledge_setup']['additional_documents'].append(extra)
                client.setup(actor_ref=case.get('actor') or 'user_a')
                setup_knowledge(client, ev, save, {'base_corpus': {'documents': []}}, rag_case)
                from scenario_client import login_merchant
                client.mheaders = login_merchant(client.merchant, client.config)
                result, tools, failed = eq.run_turns(client, case['user_turns'])
                obs = eq.observation_from_agent(result, tools, model_channel_failed=failed,
                                                gold_mode='snapshot', setup_failed=failed)
                scores = score_support(case, obs)
            audit = (obs.get('result') or {}).get('audit') or {}
            sig = {'status': audit.get('answer_status'), 'selected': len(obs.get('selected_sku_keys') or []),
                   'channel': None}
            try:
                import pymysql  # noqa
            except Exception:
                pass
            print('%-12s %-8s sel=%s status=%s' % (case['case_id'], scores.get('outcome'),
                                                   sig['selected'], sig['status']))
            results.append((case['case_id'], scores.get('outcome'), scores))
        except Exception as error:
            print('%-12s ERROR %s: %s' % (case['case_id'], type(error).__name__, str(error)[:120]))
            results.append((case['case_id'], 'error', str(error)[:120]))
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    n_pass = sum(1 for _, o, _ in results if o == 'pass')
    print('--- %d/%d pass' % (n_pass, len(results)))
    return results


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    line = 'support' if '--line' in sys.argv and 'support' in sys.argv else 'shopping'
    run_cases(line, set(args))
