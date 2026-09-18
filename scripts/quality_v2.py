"""quality-v2 scoring. Public names only; no composite score; holdout stays sealed."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import unicodedata

from runtime import ROOT

CONTRACT_DIR = ROOT / 'evals/quality-v2'
CONTRACT_JSON = CONTRACT_DIR / 'metrics-contract.json'
HOLDOUT_DIR = CONTRACT_DIR / 'holdout'
FREEZE_MANIFEST = HOLDOUT_DIR / 'freeze-manifest.json'
SHOPPING_CATALOG = CONTRACT_DIR / 'shopping/catalog-snapshot.json'
SHOPPING_DEV = CONTRACT_DIR / 'shopping/dev.jsonl'
SHOPPING_HOLDOUT = CONTRACT_DIR / 'shopping/holdout.jsonl'
SHOPPING_MANIFEST = CONTRACT_DIR / 'shopping/manifest.json'
SUPPORT_DEV = CONTRACT_DIR / 'support/dev.jsonl'
SUPPORT_HOLDOUT = CONTRACT_DIR / 'support/holdout.jsonl'
SUPPORT_MANIFEST = CONTRACT_DIR / 'support/manifest.json'
# holdout-2：独立密封留出（holdout-1 已烧毁，其文件仅存证不改动）。
SHOPPING_HOLDOUT2 = CONTRACT_DIR / 'shopping/holdout2.jsonl'
SUPPORT_HOLDOUT2 = CONTRACT_DIR / 'support/holdout2.jsonl'
# holdout-3：v15 基线后的下一份密封留出（holdout-1/2 均已烧毁）。
SHOPPING_HOLDOUT3 = CONTRACT_DIR / 'shopping/holdout3.jsonl'
SUPPORT_HOLDOUT3 = CONTRACT_DIR / 'support/holdout3.jsonl'
HOLDOUT_MANIFESTS = {'shopping': CONTRACT_DIR / 'shopping/holdout-manifest.json',
                     'support': CONTRACT_DIR / 'support/holdout-manifest.json'}
ARTIFACTS_DIR = ROOT / 'artifacts/quality-v2'
LEDGER_PATH = ARTIFACTS_DIR / 'rerun-ledger.jsonl'


class AnnotationError(ValueError):
    """Dataset annotation is self-inconsistent. Fails the whole run; never setup_failed."""


def load_json(path):
    return json.loads(Path(path).read_text())


def load_jsonl(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def contract():
    return load_json(CONTRACT_JSON)


def freeze_manifest():
    if FREEZE_MANIFEST.exists():
        return load_json(FREEZE_MANIFEST)
    return None


def refuse_holdout(split):
    if split not in ('holdout', 'holdout2', 'holdout3'):
        return
    # Both sealed splits ride on the same dev-freeze artifact; per-line seals
    # are additionally enforced by holdout_ready/holdout2_ready at run time.
    if freeze_manifest() is None:
        raise ValueError(split + '_sealed_questions_not_authored')


def provenance():
    record = {'workdir': str(ROOT), 'contract_sha256': digest(CONTRACT_JSON),
              'scorer_sha256': {name: digest(ROOT / 'scripts' / name)
                                for name in ('quality_v2.py', 'eval_quality_v2.py')}}
    try:
        record['git_head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        record['working_diff_sha256'] = sha256(subprocess.check_output(
            ['git', 'diff', '--binary', 'HEAD'], cwd=ROOT)).hexdigest()
    except (subprocess.CalledProcessError, FileNotFoundError):
        record['git_head'] = None
        record['working_diff_sha256'] = None
    return record


def _fold(text):
    return unicodedata.normalize('NFKC', str(text or '')).casefold()


def sku_satisfies(sku, constraints):
    quantity = constraints.get('quantity') or 1
    if sku.get('status') != 1:
        return False
    if type(sku.get('stock')) is not int or sku['stock'] < quantity:
        return False
    price = sku.get('price_cents')
    if type(price) is not int:
        return False
    minimum = constraints.get('min_price_cents') or 0
    maximum = constraints.get('budget_max_cents')
    if price < minimum or (maximum is not None and price > maximum):
        return False
    if sku.get('product_id') in (constraints.get('excluded_product_ids') or []):
        return False
    if sku.get('sku_key') in (constraints.get('excluded_sku_keys') or []):
        return False
    category = constraints.get('category_id')
    if category is not None and sku.get('categoryId') != category:
        return False
    text = _fold(str(sku.get('productName') or '') + ' ' + str(sku.get('specification') or ''))
    if any(_fold(term) not in text for term in constraints.get('required_terms') or []):
        return False
    if any(_fold(term) in text for term in constraints.get('excluded_terms') or []):
        return False
    return True


def catalog_index(catalog=None):
    catalog = catalog or load_json(SHOPPING_CATALOG)
    return {row['sku_key']: row for row in catalog['skus']}


def align_to_snapshot(products, catalog=None):
    index = catalog_index(catalog)
    by_sig = {(_fold(row['productName']), _fold(row['specification']), row['price_cents']): row
              for row in index.values()}
    aligned = []
    for row in products or []:
        gold = by_sig.get((_fold(row.get('productName')), _fold(row.get('specification')), row.get('price_cents')))
        if gold:
            aligned.append({**row, **gold})
        else:
            aligned.append({**row, 'sku_key': row.get('sku_key')})
    return aligned


def remap_observation(observation, catalog=None):
    products = list(observation.get('products') or [])
    aligned = align_to_snapshot(products, catalog)
    remap = {}
    for before, after in zip(products, aligned):
        if before.get('sku_key') and after.get('sku_key'):
            remap[before['sku_key']] = after['sku_key']
    def keys(values):
        return [remap.get(key, key) for key in (values or [])]
    return {**observation, 'products': aligned, 'selected_sku_keys': keys(observation.get('selected_sku_keys')),
            'comparison_sku_keys': keys(observation.get('comparison_sku_keys'))}


def catalog_overlay_plan(manifest, catalog=None):
    gold = list((catalog or load_json(SHOPPING_CATALOG))['skus'])
    products = list(manifest['products'])
    if len(products) < len(gold):
        raise ValueError('scenario_product_count_below_snapshot')
    # sys_category.category_id is varchar(5); snapshot "furniture" does not fit.
    live_category = {'desk': 'desk', 'audio': 'audio', 'acc': 'acc', 'furniture': 'furn'}
    categories = list(dict.fromkeys(live_category[row['categoryId']] for row in gold))
    if any(len(category) > 5 for category in categories):
        raise ValueError('live_category_id_exceeds_varchar5')
    plan = []
    for sku, product_id in zip(gold, products):
        live = [row for row in manifest['skus'] if row['productId'] == product_id]
        primary = next(row for row in live if row.get('specIndex') == 0)
        extras = [row for row in live if row.get('specIndex') != 0]
        plan.append({
            'product_id': product_id, 'gold_sku_key': sku['sku_key'],
            'productName': sku['productName'], 'specification': sku['specification'],
            'price_cents': sku['price_cents'], 'stock': sku['stock'], 'status': sku['status'],
            'categoryId': sku['categoryId'],
            'live_category_id': live_category[sku['categoryId']],
            'primary_hash': primary['propertyValueIdHash'],
            'primary_value_id': primary['propertyValueIds'],
            'extra_hashes': [row['propertyValueIdHash'] for row in extras],
        })
    return {'categories': categories, 'products': plan}


def live_support_cases(cases=None):
    return [case for case in (cases if cases is not None else load_jsonl(SUPPORT_DEV))
            if case.get('live_eligible', True)]


def observation_from_agent(result, tool_calls, *, setup_failed=False, setup_reason=None,
                           model_channel_failed=False, gold_mode='snapshot'):
    selected = []
    retrieve = {}
    comparison = result.get('comparison') or {}
    for call in tool_calls or []:
        name = call.get('tool_name')
        args = call.get('arguments_json')
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name == 'finish_answer' and isinstance(args, dict):
            selected = list(args.get('selected_sku_keys') or selected)
        if name in {'recommend_skus', 'compare_skus'}:
            data = receipt_data(call)
            retrieve = data.get('diagnostics') or {}
            if data.get('empty_reason') and not retrieve.get('empty_reason'):
                retrieve['empty_reason'] = data['empty_reason']
            if data.get('missing_targets') is not None:
                comparison = {**comparison, 'missing_targets': data.get('missing_targets'),
                              'comparison_complete': data.get('comparison_complete'),
                              'sku_keys': (data.get('comparison') or {}).get('sku_keys')}
    products = result.get('products') or []
    if not selected:
        selected = [row.get('sku_key') for row in products if row.get('sku_key')]
    return {
        'setup_failed': setup_failed, 'setup_reason': setup_reason, 'model_channel_failed': model_channel_failed,
        'gold_mode': gold_mode, 'selected_sku_keys': selected, 'products': products,
        'retrieve_diagnostics': retrieve, 'comparison_complete': result.get('comparison_complete', comparison.get('comparison_complete')),
        'missing_targets': result.get('missing_targets') or comparison.get('missing_targets') or [],
        'comparison_sku_keys': comparison.get('sku_keys') or [],
        'result': result, 'tool_calls': tool_calls,
    }


def selected_list(observation, k=4):
    """Positional slots from the agent's selection order. Unknown sku_keys stay as
    violating placeholders instead of being silently dropped."""
    products = {row.get('sku_key'): row for row in observation.get('products') or [] if row.get('sku_key')}
    keys = list(observation.get('selected_sku_keys') or [])
    if not keys:
        keys = [row.get('sku_key') for row in observation.get('products') or [] if row.get('sku_key')]
    items = []
    for key in keys[:k]:
        if key in products:
            items.append(products[key])
        else:
            items.append({'sku_key': key, 'status': None, 'stock': None, 'price_cents': None,
                          'productName': '', 'specification': '', 'unknown_sku_key': True})
    return items


def score_shopping(case, observation, catalog=None):
    if observation.get('setup_failed') or observation.get('model_channel_failed'):
        return {'line': 'shopping', 'case_id': case['case_id'], 'outcome': 'setup_failed',
                'Precision@4': None, 'Pass@1': None, 'reason': observation.get('setup_reason') or 'setup_failed'}
    skus = catalog_index(catalog)
    constraints = case['hard_constraints']
    gold = list(case.get('satisfaction_set') or [])
    kind = case.get('kind') or 'recommend'
    if observation.get('gold_mode') != 'fields':
        observation = remap_observation(observation, catalog)
    items = selected_list(observation)
    diagnostics = observation.get('retrieve_diagnostics') or {}
    popular = bool(diagnostics.get('popular_used') or diagnostics.get('copurchase_used'))

    if kind == 'compare':
        missing = list(observation.get('missing_targets') or [])
        complete = observation.get('comparison_complete')
        table_keys = list(observation.get('comparison_sku_keys') or [row['sku_key'] for row in items])
        allowed = case.get('allowed_target_terms') or []
        unrelated = []
        for key in table_keys:
            sku = skus.get(key) or next((row for row in items if row.get('sku_key') == key), None)
            text = _fold((sku or {}).get('productName', '') + ' ' + (sku or {}).get('specification', ''))
            if allowed and not any(_fold(term) in text for term in allowed):
                unrelated.append(key)
        if case.get('expected_comparison_complete') is True:
            passed = complete is True and not missing and not unrelated
        else:
            passed = complete is False and not unrelated
        if popular:
            passed = False
        return {'line': 'shopping', 'case_id': case['case_id'], 'outcome': 'pass' if passed else 'fail',
                'Precision@4': None, 'Pass@1': 1 if passed else 0,
                'comparison_complete': complete, 'missing_targets': missing, 'unrelated': unrelated}

    hits = sum(1 for sku in items if sku_satisfies(sku, constraints))
    demand = int(constraints.get('quantity') or 1)
    if demand > 1 and gold:
        # Demand-fill semantics: one satisfying SKU bought at the requested quantity
        # fully serves the user; slots equal units demanded, not distinct SKUs listed.
        hits = min(4, demand) if hits else 0
    precision = hits / 4
    if not gold:
        empty_ok = diagnostics.get('empty_reason') in (contract()['shopping']['empty_reasons_ok'])
        passed = (not items and not popular and empty_ok)
        # empty_set_honesty: in an empty-satisfaction case the honest outcome IS the
        # pass condition — empty list + legitimate reason + no popular backfill.
        return {'line': 'shopping', 'case_id': case['case_id'], 'outcome': 'pass' if passed else 'fail',
                'Precision@4': None, 'Pass@1': 1 if passed else 0, 'empty_reason': diagnostics.get('empty_reason'),
                'empty_set_honesty': 1 if passed else 0}

    selected_keys = [sku['sku_key'] for sku in items]
    ceiling = min(4, len(gold)) / 4
    if observation.get('gold_mode') == 'fields':
        in_gold = any(sku_satisfies(sku, constraints) for sku in items)
        no_violators = all(sku_satisfies(sku, constraints) for sku in items)
    else:
        in_gold = any(key in gold for key in selected_keys)
        no_violators = all(sku_satisfies(sku, constraints) and sku['sku_key'] in gold for sku in items)
    passed = in_gold and no_violators and not popular
    # violation_free@1: recommend trials with a non-empty selection only (compare
    # scores completeness, empty-satisfaction cases score honesty — both stay null).
    violation_free = (1 if sku_satisfies(items[0], constraints) else 0) if items else None
    return {'line': 'shopping', 'case_id': case['case_id'], 'outcome': 'pass' if passed else 'fail',
            'Precision@4': precision, 'Precision@4_ceiling': ceiling,
            # NDCG-style normalization against the achievable ceiling: same slots,
            # same hits — the ratio only answers "how close to this case's maximum".
            # Capped at 1.0; demand-fill overshoot stays visible in the raw column.
            'Precision@4/ceiling': min(precision / ceiling, 1.0) if ceiling else None,
            'Pass@1': 1 if passed else 0, 'hits': hits, 'selected': selected_keys,
            'violation_free@1': violation_free}


def receipt_data(call):
    receipt = call.get('receipt') if isinstance(call.get('receipt'), dict) else None
    if receipt is None and isinstance(call.get('receipt_json'), (str, dict)):
        raw = call['receipt_json']
        receipt = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(receipt, dict) and isinstance(receipt.get('data'), dict):
        return receipt['data']
    if isinstance(call.get('data'), dict):
        return call['data']
    return receipt if isinstance(receipt, dict) else {}


def last_real_search(tool_calls):
    found = None
    for call in tool_calls or []:
        if call.get('tool_name') != 'search_knowledge':
            continue
        data = receipt_data(call)
        retrieval = data.get('retrieval') or {}
        if data.get('candidates') or retrieval.get('final_depth') is not None:
            found = data
    return found


def recall_at_k(gold_doc_ids, candidates, k):
    gold = list(dict.fromkeys(gold_doc_ids or []))
    if not gold:
        return None
    ranked = []
    for row in candidates or []:
        doc_id = row.get('doc_id') if isinstance(row, dict) else row
        if doc_id and doc_id not in ranked:
            ranked.append(doc_id)
    return len(set(gold) & set(ranked[:k])) / len(gold)


def dedup_ranks(candidates):
    """doc_id -> 1-based rank in the deduplicated candidate order (same order
    recall_at_k scores against; duplicate doc_ids keep their first position)."""
    ranks = {}
    for row in candidates or []:
        doc_id = row.get('doc_id') if isinstance(row, dict) else row
        if doc_id and doc_id not in ranks:
            ranks[doc_id] = len(ranks) + 1
    return ranks


def mrr_at_k(gold_doc_ids, candidates, k=8):
    """Mean reciprocal rank over gold docs; a gold doc ranked beyond k (or absent)
    contributes 0, matching Recall@k's null-vs-zero semantics."""
    gold = list(dict.fromkeys(gold_doc_ids or []))
    if not gold:
        return None
    ranks = dedup_ranks(candidates)
    return mean(1 / ranks[doc] if ranks.get(doc, k + 1) <= k else 0.0 for doc in gold)


def recall_at_1_strict(gold_doc_ids, candidates):
    """1.0 only when every gold doc sits at rank 1 of the deduped order — with
    distinct doc_ids that means single-gold-at-top; multi-gold trials score 0."""
    gold = list(dict.fromkeys(gold_doc_ids or []))
    if not gold:
        return None
    ranks = dedup_ranks(candidates)
    return 1.0 if all(ranks.get(doc) == 1 for doc in gold) else 0.0


def context_precision_at_k(gold_doc_ids, candidates, k=8):
    """RAGAS-style rank-weighted precision with binary gold: at each hit position i,
    precision-so-far = hits_up_to_i / i; total = sum(precision@i) / |gold|."""
    gold = set(dict.fromkeys(gold_doc_ids or []))
    if not gold:
        return None
    ranked = []
    for row in candidates or []:
        doc_id = row.get('doc_id') if isinstance(row, dict) else row
        if doc_id and doc_id not in ranked:
            ranked.append(doc_id)
    hits, total = 0, 0.0
    for index, doc_id in enumerate(ranked[:k], start=1):
        if doc_id in gold:
            hits += 1
            total += hits / index
    return total / len(gold)


NEGATION_WINDOW = 8
NEGATION_CUES = ('不', '没', '未', '非', '别', '无', '勿', '莫')


def _uncued_hits(needle, text):
    """Occurrences of needle not preceded by a negation cue; honest negations don't count."""
    haystack, needle = _fold(text), _fold(needle)
    hits, start = [], 0
    if not needle:
        return hits
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return hits
        window = haystack[max(0, index - NEGATION_WINDOW):index]
        if not any(cue in window for cue in NEGATION_CUES):
            hits.append(index)
        start = index + 1


def answer_text(result):
    return str((result or {}).get('answer') or '')


def score_faithfulness(case, result, *, safety_override=None):
    if safety_override == 'citation_no_longer_visible':
        return None
    claims = list(case.get('checkable_claims') or [])
    if not claims:
        return None
    citations = result.get('citations') or []
    if not citations:
        return 0.0
    cited = ' '.join((row.get('content') or row.get('text') or '') for row in citations)
    said = _fold(answer_text(result))
    folded_cited = _fold(cited)
    supported = 0
    for claim in claims:
        needle = _fold(claim.get('text') or claim.get('span') or '')
        if needle and needle in said and needle in folded_cited:
            supported += 1
    return supported / len(claims)


def score_support(case, observation):
    if observation.get('setup_failed') or observation.get('model_channel_failed'):
        return {'line': 'support', 'case_id': case['case_id'], 'outcome': 'setup_failed',
                'Recall@8': None, 'Faithfulness': None, 'Pass@1': None,
                'reason': observation.get('setup_reason') or 'setup_failed'}
    result = observation.get('result') or {}
    search = last_real_search(observation.get('tool_calls') or [])
    candidates = (search or {}).get('candidates') or []
    gold = list(case.get('relevant_doc_ids') or [])
    recall = recall_at_k(gold, candidates, 8)
    diagnostic = recall_at_k(gold, candidates, 4)
    mrr = mrr_at_k(gold, candidates, 8)
    recall1 = recall_at_1_strict(gold, candidates)
    context_precision = context_precision_at_k(gold, candidates, 8)
    if case.get('expected_retrieval') is False and gold:
        raise AnnotationError('chitchat_cannot_have_relevant_docs:' + case['case_id'])
    if case.get('expected_retrieval') is False:
        recall = None
        diagnostic = None
        mrr = recall1 = context_precision = None
    forbidden = set(case.get('forbidden_doc_ids') or [])
    cited = {row.get('doc_id') for row in result.get('citations') or [] if row.get('doc_id')}
    cand_ids = {row.get('doc_id') for row in candidates if isinstance(row, dict)}
    leaked = bool((cited | cand_ids) & forbidden)
    said = answer_text(result)
    forbidden_claim_hit = [item for item in case.get('forbidden_claims') or []
                           if _fold(item) in _fold(said)]
    must_not_claim_hit = [item for item in case.get('must_not_claim') or []
                          if _uncued_hits(item, said)]
    claim_hit = bool(forbidden_claim_hit or must_not_claim_hit)
    # Contract v3: public Faithfulness is judge-based (apply_judge_faithfulness fills
    # it); the exact-substring rule score stays as a diagnostic column.
    rule_faithfulness = score_faithfulness(case, result, safety_override=result.get('safety_override'))
    ticket = (result.get('ticket') or observation.get('ticket') or {})
    ticket_id = ticket.get('ticket_id') if isinstance(ticket, dict) else None
    handoff = result.get('answer_status') == 'needs_human' and bool(ticket_id)
    expected_handoff = bool(case.get('expected_handoff'))
    pass_handoff = handoff if expected_handoff else (not handoff and result.get('answer_status') != 'needs_human')
    if case.get('allow_insufficient') and result.get('answer_status') == 'insufficient' and not ticket_id:
        pass_handoff = True
    # allow_handoff (P3 D4): once-published-then-expired/withdrawn material —
    # insufficient and a real ticket are both honest closures of the same
    # epistemic state. needs_human without a ticket still fails either way.
    if case.get('allow_handoff') and handoff:
        pass_handoff = True
    outcome = 'fail' if leaked or claim_hit or not pass_handoff else 'pass'
    if recall is None and rule_faithfulness is None and case.get('expected_retrieval') is False:
        outcome = 'pass' if pass_handoff and not claim_hit else 'fail'
    return {'line': 'support', 'case_id': case['case_id'], 'outcome': outcome,
            'Recall@8': recall, 'Recall@4_diagnostic': diagnostic,
            'Recall@1': recall1, 'MRR@8': mrr, 'Context_Precision@8': context_precision,
            'Faithfulness': None if case.get('checkable_claims') else None,
            'Faithfulness_rule': rule_faithfulness,
            'Pass@1': 1 if pass_handoff and not leaked and not claim_hit else 0, 'handoff': handoff,
            'expected_handoff': expected_handoff, 'allow_handoff': bool(case.get('allow_handoff')),
            'forbidden_leak': leaked, 'forbidden_claim_hit': forbidden_claim_hit,
            'must_not_claim_hit': must_not_claim_hit}


def mean(values):
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def wilson_ci(value, n, *, z=1.96):
    """Wilson score interval for a [0,1] mean over n observations.

    Exact for binary outcomes (Pass@1). For fractional metrics (Precision@4,
    Recall@8, Faithfulness, ...) it is the documented score-interval
    approximation on the pooled observations; dispersion is additionally
    visible in per-case trial tables, never hidden inside the CI."""
    if value is None or not n:
        return None
    p = min(max(value, 0.0), 1.0)
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    spread = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / denominator
    return [round(center - spread, 4), round(center + spread, 4)]


def _corpus_for(case):
    parts = []
    for doc_id in case.get('visible_doc_ids') or []:
        path = ROOT / 'fixtures/knowledge' / (doc_id + '.md')
        parts.append(path.read_text() if path.exists() else '')
    setup = case.get('knowledge_setup') or {}
    for doc in (setup.get('additional_documents') or []) + (setup.get('documents') or []):
        body = doc.get('body')
        if not body and doc.get('source_uri'):
            path = ROOT / doc['source_uri']
            body = path.read_text() if path.exists() else ''
        parts.append(body or '')
    return '\n'.join(parts)


def validate_shopping_case(case, skus, problems, split='development'):
    cid = case.get('case_id')
    if not cid:
        problems.append('shopping: case_id_missing')
        return
    if case.get('split') != split:
        problems.append(f'{cid}: split_mismatch:{case.get("split")}')
    for key in case.get('satisfaction_set') or []:
        if key not in skus:
            problems.append(f'{cid}: satisfaction_key_missing:{key}')
    if (case.get('kind') or 'recommend') == 'compare':
        if case.get('expected_comparison_complete') is None:
            problems.append(f'{cid}: compare_needs_expected_comparison_complete')
        if not case.get('allowed_target_terms'):
            problems.append(f'{cid}: compare_needs_allowed_target_terms')
        return
    derived = {key for key, sku in skus.items() if sku_satisfies(sku, case['hard_constraints'])}
    if set(case.get('satisfaction_set') or []) != derived:
        problems.append(f'{cid}: satisfaction_set_mismatch; derived={sorted(derived)}')
    if case.get('expected_pass') not in {0, 1}:
        problems.append(f'{cid}: expected_pass_not_boolean')


def validate_support_case(case, problems, split='development'):
    cid = case.get('case_id')
    if not cid:
        problems.append('support: case_id_missing')
        return
    if case.get('split') != split:
        problems.append(f'{cid}: split_mismatch:{case.get("split")}')
    if case.get('expected_retrieval') is False and case.get('relevant_doc_ids'):
        problems.append(f'{cid}: chitchat_cannot_have_relevant_docs')
    if case.get('allow_handoff') and (case.get('expected_handoff') or not case.get('allow_insufficient')):
        problems.append(f'{cid}: allow_handoff_requires_expected_handoff_false_and_allow_insufficient')
    if set(case.get('forbidden_doc_ids') or []) & set(case.get('relevant_doc_ids') or []):
        problems.append(f'{cid}: forbidden_doc_in_relevant_set')
    if case.get('actor') not in {None, 'user_a', 'user_b', 'visitor'}:
        problems.append(f'{cid}: unsupported_actor')
    corpus = _fold(_corpus_for(case))
    for claim in case.get('checkable_claims') or []:
        needle = _fold(claim.get('text') or claim.get('span') or '')
        if not needle:
            problems.append(f'{cid}: empty_checkable_claim')
        elif needle not in corpus:
            problems.append(f'{cid}: claim_not_in_visible_corpus:{needle[:24]}')
        if claim.get('scope') not in ('essential', 'peripheral'):
            problems.append(f'{cid}: claim_scope_missing:{claim.get("id") or needle[:12]}')
    for field in ('forbidden_claims', 'must_not_claim'):
        for item in case.get(field) or []:
            if not str(item).strip():
                problems.append(f'{cid}: empty_{field}')


def dataset_paths(split='development'):
    if split == 'development':
        return {'shopping': SHOPPING_DEV, 'support': SUPPORT_DEV}
    if split == 'holdout':
        return {'shopping': SHOPPING_HOLDOUT, 'support': SUPPORT_HOLDOUT}
    if split == 'holdout2':
        return {'shopping': SHOPPING_HOLDOUT2, 'support': SUPPORT_HOLDOUT2}
    if split == 'holdout3':
        return {'shopping': SHOPPING_HOLDOUT3, 'support': SUPPORT_HOLDOUT3}
    raise ValueError('unknown_split:' + split)


def validate_dev_sets(lines=('shopping', 'support'), split='development'):
    """Upfront annotation consistency. A wrong dataset fails the run, never the case."""
    problems = []
    paths = dataset_paths(split)
    if 'shopping' in lines:
        skus = catalog_index()
        for case in load_jsonl(paths['shopping']):
            validate_shopping_case(case, skus, problems, split)
    if 'support' in lines:
        for case in load_jsonl(paths['support']):
            validate_support_case(case, problems, split)
    if problems:
        raise AnnotationError(f'{split}_set_annotation_error\n' + '\n'.join(problems))
    return True


def holdout_ready(lines=('shopping', 'support')):
    missing = [line for line in lines if not HOLDOUT_MANIFESTS[line].exists()]
    if missing:
        raise ValueError('holdout_questions_not_authored:' + ','.join(missing))
    return True


HOLDOUT2_MANIFESTS = {'shopping': CONTRACT_DIR / 'shopping/holdout2-manifest.json',
                      'support': CONTRACT_DIR / 'support/holdout2-manifest.json'}


HOLDOUT3_MANIFESTS = {'shopping': CONTRACT_DIR / 'shopping/holdout3-manifest.json',
                      'support': CONTRACT_DIR / 'support/holdout3-manifest.json'}


def holdout3_ready(lines=('shopping', 'support')):
    """Seal gate for holdout-3: runable only after every line's manifest is stamped.
    Draft stage validates offline but never runs — first test is final test."""
    missing = [line for line in lines if not HOLDOUT3_MANIFESTS[line].exists()]
    if missing:
        raise ValueError('holdout3_seal_pending_user_approval:' + ','.join(missing))
    return True


def holdout2_ready(lines=('shopping', 'support')):
    """Seal gate for holdout-2: runable only after every line's manifest is stamped.

    Draft stage (questions authored, user review pending) can validate offline
    but never run: first test is final test, so nothing executes before the seal."""
    missing = [line for line in lines if not HOLDOUT2_MANIFESTS[line].exists()]
    if missing:
        raise ValueError('holdout2_seal_pending_user_approval:' + ','.join(missing))
    return True


def handoff_f1(rows):
    """P/R/F1 of "opened a persistent ticket" (the compiled final state behind
    Pass@1's handoff face) against expected_handoff. allow_handoff cases accept
    both closures, so they are undecidable negatives: excluded from the
    denominator and counted separately."""
    eligible = [row for row in rows
                if row.get('outcome') != 'setup_failed' and not row.get('allow_handoff')]
    tp = sum(1 for row in eligible if row.get('expected_handoff') and row.get('handoff'))
    fp = sum(1 for row in eligible if not row.get('expected_handoff') and row.get('handoff'))
    fn = sum(1 for row in eligible if row.get('expected_handoff') and not row.get('handoff'))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if precision is None or recall is None or precision + recall == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {'precision': precision, 'recall': recall, 'f1': f1,
            'tp': tp, 'fp': fp, 'fn': fn, 'denominator': len(eligible),
            'excluded_allow_handoff': sum(1 for row in rows if row.get('outcome') != 'setup_failed'
                                          and row.get('allow_handoff'))}


def aggregate_line(name, rows, metric_names, trial_level_names=()):
    scored = [row for row in rows if row.get('outcome') != 'setup_failed']
    setup_failed = [row for row in rows if row.get('outcome') == 'setup_failed']
    summary = {'line': name, 'n': len(rows), 'n_scored': len(scored), 'n_setup_failed': len(setup_failed),
               'n_pass': sum(1 for row in scored if row.get('outcome') == 'pass')}
    by_case = {}
    for row in rows:
        by_case.setdefault(row.get('case_id'), []).append(row)
    trial_numbers = [row['trial'] for row in rows if row.get('trial') is not None]
    if trial_numbers:
        # k-trial run: every row is one trial, so n/n_scored count trials. The
        # headline keeps every case at equal weight via that case's trial mean.
        summary['trials'] = max(trial_numbers)
        summary['n_cases'] = len(by_case)
        scored_by_case = {case_id: [row for row in case_rows if row.get('outcome') != 'setup_failed']
                          for case_id, case_rows in by_case.items()}
        k = summary['trials']
        eligible = [case_rows for case_rows in scored_by_case.values() if len(case_rows) == k]
        all_pass = sum(1 for case_rows in eligible
                       if all(row.get('outcome') == 'pass' for row in case_rows))
        summary['pass^k'] = {'k': k, 'n_eligible': len(eligible), 'n_all_pass': all_pass,
                             'value': all_pass / len(eligible) if eligible else None}
        summary['flip_cases'] = sorted(case_id for case_id, case_rows in scored_by_case.items()
                                       if len({row.get('outcome') for row in case_rows}) > 1)
    else:
        scored_by_case = {None: scored}
    # Denominators next to every headline so a 1.0 over 10 cases can't pose as 1.0 over all.
    trial_level_names = tuple(trial_level_names)
    all_metrics = tuple(metric_names) + trial_level_names
    summary['denominators'] = {metric: sum(1 for row in scored if row.get(metric) is not None)
                               for metric in all_metrics}
    for metric in metric_names:
        summary[metric] = mean(mean(row.get(metric) for row in case_rows)
                               for case_rows in scored_by_case.values())
    # Tier-1 diagnostic columns aggregate at trial level (each scored trial is one
    # observation), unlike the case-macro headlines above.
    for metric in trial_level_names:
        summary[metric] = mean(row.get(metric) for row in scored)
    summary['ci95_wilson'] = {metric: wilson_ci(summary[metric], summary['denominators'][metric])
                              for metric in all_metrics}
    return summary


def trial_table(rows):
    """Per-case k-trial outcomes: pass rate per case, flips made visible."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row['case_id'], []).append(row)
    cases = []
    for case_id in sorted(grouped):
        case_rows = sorted(grouped[case_id], key=lambda row: row.get('trial') or 1)
        scored = [row for row in case_rows if row.get('outcome') != 'setup_failed']
        passes = sum(1 for row in scored if row.get('outcome') == 'pass')
        cases.append({
            'case_id': case_id,
            'trials': [{'trial': row.get('trial') or 1, 'outcome': row.get('outcome')}
                       for row in case_rows],
            'n_scored': len(scored),
            'passes': passes,
            'pass_rate': passes / len(scored) if scored else None,
            'flipped': len({row.get('outcome') for row in scored}) > 1,
        })
    return {'n_cases': len(cases),
            'n_flipped': sum(1 for row in cases if row['flipped']),
            'cases': cases}


def synthetic_shopping_observation(case, catalog=None):
    skus = catalog_index(catalog)
    gold = list(case.get('satisfaction_set') or [])
    if case.get('kind') == 'compare':
        picked = []
        for term in case.get('allowed_target_terms') or []:
            for sku in skus.values():
                if _fold(term) in _fold(sku['productName']) and sku['sku_key'] not in {row['sku_key'] for row in picked}:
                    picked.append(sku)
                    break
        missing = [] if case.get('expected_comparison_complete') else ['火星飞船']
        return {'selected_sku_keys': [row['sku_key'] for row in picked], 'products': picked,
                'comparison_complete': case.get('expected_comparison_complete'), 'missing_targets': missing,
                'comparison_sku_keys': [row['sku_key'] for row in picked],
                'retrieve_diagnostics': {'popular_used': False, 'copurchase_used': False, 'empty_reason': None}}
    if not gold:
        return {'selected_sku_keys': [], 'products': [],
                'retrieve_diagnostics': {'popular_used': False, 'copurchase_used': False,
                                         'empty_reason': 'hard_constraint_unsatisfied'}}
    picked = [skus[key] for key in gold if key in skus][:4]
    return {'selected_sku_keys': [row['sku_key'] for row in picked], 'products': picked,
            'retrieve_diagnostics': {'popular_used': False, 'copurchase_used': False}}


def synthetic_support_observation(case):
    gold = list(case.get('relevant_doc_ids') or [])
    claims = list(case.get('checkable_claims') or [])
    if case.get('case_id') == 'sup-d-24':
        return {'result': {'answer': '引用已失效，转人工核实。', 'answer_status': 'needs_human', 'citations': [],
                           'safety_override': 'citation_no_longer_visible', 'ticket': {'ticket_id': 'ticket-cleared'}},
                'tool_calls': [{'tool_name': 'search_knowledge',
                                'data': {'candidates': [{'doc_id': '02-payment'}], 'retrieval': {'final_depth': 8}}}]}
    said = ' '.join(item['text'] for item in claims)
    citations = [{'doc_id': gold[0], 'version': 1, 'content': said}] if gold and claims else []
    if case.get('expected_handoff'):
        result = {'answer': said or '两份资料冲突，已建工单转人工。', 'answer_status': 'needs_human',
                  'citations': citations, 'ticket': {'ticket_id': 'ticket-1'}}
    elif case.get('allow_insufficient') and not gold:
        result = {'answer': '当前没有可引用的已发布资料。', 'answer_status': 'insufficient', 'citations': []}
    else:
        result = {'answer': said or '已按店内资料回答。', 'answer_status': 'answered',
                  'citations': citations or (
                      [{'doc_id': gold[0], 'version': 1, 'content': '已发布政策原文'}] if gold else [])}
    if case.get('expected_retrieval') is False:
        tools = []
    else:
        ranked = [{'doc_id': doc} for doc in gold] or ([{'doc_id': '01-store-scope'}] if case.get('allow_insufficient') else [])
        ranked = [row for row in ranked if row['doc_id'] not in set(case.get('forbidden_doc_ids') or [])]
        tools = [{'tool_name': 'search_knowledge', 'data': {'candidates': ranked, 'retrieval': {'final_depth': 8}}}]
    return {'result': result, 'tool_calls': tools}


def self_check_scores():
    validate_dev_sets()
    shopping = [score_shopping(case, synthetic_shopping_observation(case)) for case in load_jsonl(SHOPPING_DEV)]
    support = [score_support(case, synthetic_support_observation(case)) for case in load_jsonl(SUPPORT_DEV)]
    return shopping, support


def _iter_case_rows(summary):
    for line in ('shopping', 'support'):
        for row in (summary.get('cases') or {}).get(line) or []:
            yield row


def prior_setup_failures(exclude_dir=None, *, artifacts_dir=None):
    """case_id -> latest prior setup_failed record across earlier run summaries."""
    exclude = Path(exclude_dir).name if exclude_dir else None
    root = Path(artifacts_dir) if artifacts_dir else ARTIFACTS_DIR
    found = {}
    for path in sorted(root.glob('*/summary.json')):
        run_dir = path.parent.name
        if run_dir == exclude:
            continue
        try:
            summary = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for row in _iter_case_rows(summary):
            if row.get('outcome') == 'setup_failed':
                found[row['case_id']] = {'prior_run': run_dir, 'prior_reason': row.get('reason')}
    return found


def append_rerun_ledger(output_dir, report, *, artifacts_dir=None):
    """Durable ledger: every setup_failed case and every rerun that resolves it.
    With k trials a case logs one entry, carrying its per-trial outcomes."""
    output_dir = Path(output_dir)
    run_id = output_dir.name
    prior = prior_setup_failures(output_dir, artifacts_dir=artifacts_dir)
    grouped = {}
    for row in _iter_case_rows(report):
        grouped.setdefault(row['case_id'], []).append(row)
    entries = []
    for case_id, case_rows in grouped.items():
        setup_failed = [row for row in case_rows if row.get('outcome') == 'setup_failed']
        history = prior.get(case_id)
        if not history and not setup_failed:
            continue
        if len(setup_failed) == len(case_rows):
            current = 'setup_failed'
        elif setup_failed:
            current = 'partial_setup_failed'
        else:
            distinct = {row.get('outcome') for row in case_rows}
            current = next(iter(distinct)) if len(distinct) == 1 else 'mixed'
        entry = {'run_id': run_id, 'case_id': case_id, 'line': case_rows[0].get('line'),
                 'prior_run': history['prior_run'] if history else None,
                 'prior_reason': history['prior_reason'] if history else None,
                 'current_outcome': current}
        if not history and setup_failed:
            entry['status'] = 'pending_rerun'
        if any(row.get('trial') is not None for row in case_rows):
            entry['trial_outcomes'] = [{'trial': row.get('trial'), 'outcome': row.get('outcome')}
                                       for row in case_rows]
        entries.append(entry)
    if entries:
        ledger = Path(artifacts_dir) / 'rerun-ledger.jsonl' if artifacts_dir else LEDGER_PATH
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open('a', encoding='utf-8') as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    report['rerun_ledger'] = entries
    (output_dir / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return entries


def write_report(output_dir, shopping, support, *, official=False, partial=False, synthetic=False,
                 trials=1):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    support_summary = aggregate_line('support', support, ('Recall@8', 'Faithfulness',
                                                          'Faithfulness_rule', 'Faithfulness_answer_side',
                                                          'Peripheral_coverage', 'Pass@1'),
                                     trial_level_names=('Recall@1', 'MRR@8', 'Context_Precision@8'))
    support_summary['handoff_f1'] = handoff_f1(support)
    report = {
        'schema_version': 'quality-v2-report-v2',
        'official': official,
        'partial': partial,
        'synthetic': synthetic,
        'trials': trials,
        'composite_score': None,
        'note': '主线分开展示，不合成总分。'
                + (' 本 run 仅重跑部分案例，不是完整开发集成绩。' if partial else '')
                + (' 合成观测自检，只验证评分链路，不是系统成绩。' if synthetic else '')
                + (f' 导购/客服每题独立 {trials} 次试验（各自 fresh scenario）；'
                   f'pass^k=全部 k 次试验都通过的题占比。' if trials > 1 else ''),
        'provenance': provenance(),
        'shopping': aggregate_line('shopping', shopping, ('Precision@4/ceiling', 'Precision@4',
                                                        'Precision@4_ceiling', 'Pass@1'),
                                   trial_level_names=('violation_free@1', 'empty_set_honesty')),
        'support': support_summary,
        'cases': {'shopping': shopping, 'support': support},
    }
    if trials > 1:
        report['per_case_trials'] = {name: trial_table(rows)
                                     for name, rows in (('shopping', shopping), ('support', support))
                                     if any(row.get('trial') is not None for row in rows)}
    path = output_dir / 'summary.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report
