"""Install reviewed synthetic policies in the owned Growth DB; never touches Java tables."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from runtime import ROOT, ENV_FILE, model_env, parse_env
from smartlect.auth import ActorContext
from smartlect.knowledge import KnowledgeStore
from smartlect.provider import Provider


async def seed(live):
    config = {**parse_env(ENV_FILE), **model_env()}
    os.environ.update(config)
    knowledge = KnowledgeStore()
    knowledge.initialize()
    publisher = ActorContext(subject_type='merchant', actor_id='fixture-publisher',
                             permissions=('admin:legacy',), session_id='local-fixture-installer')
    provider = Provider(config)
    existing = knowledge.list_documents(publisher)
    records, traces = [], []
    for path in sorted((ROOT / 'fixtures/knowledge').glob('*.md')):
        body = path.read_text()
        digest = hashlib.sha256(body.encode()).hexdigest()
        matched = [doc for doc in existing if doc['doc_id'] == path.stem and doc['checksum'] == digest and doc['status'] == 'PUBLISHED']
        if matched:
            records.append({'doc_id': path.stem, 'version': matched[0]['version'], 'status': 'retained'})
            continue
        document = knowledge.create_draft(publisher, {'doc_id': path.stem, 'title': body.splitlines()[0].lstrip('# '),
            'source_uri': str(path.relative_to(ROOT)), 'body': body, 'acl': 'PUBLIC',
            'valid_from': '2026-01-01T00:00:00Z', 'valid_until': '2027-12-31T23:59:59Z'})
        chunks = knowledge.draft_chunks(publisher, path.stem, document['version'])
        if live:
            vectors = []
            for start in range(0, len(chunks), 10):
                batch = chunks[start:start + 10]
                result = await provider.embed([c['content'] for c in batch], on_trace=traces.append,
                                              prompt_version='fixture-index-v1')
                meta = result['metadata']
                vectors.extend({'chunk_id': c['chunk_id'], 'vector': v} for c, v in zip(batch, result['embeddings'], strict=True))
            knowledge.set_embeddings(publisher, path.stem, document['version'], model=meta['model_id'],
                                     index_version=f"{meta['model_id']}:d{meta['dimensions']}:v1", vectors=vectors)
        knowledge.publish(publisher, path.stem, document['version'])
        records.append({'doc_id': path.stem, 'version': document['version'], 'chunks': len(chunks),
                        'mode': 'hybrid-indexed' if live else 'lexical', 'checksum': digest})
    result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'documents': records, 'model_attempts': traces,
              'live_embeddings_requested': live, 'answer_quality_evaluated': False}
    output = ROOT / 'artifacts/f2-knowledge-index.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'documents': len(records), 'provider_attempts': len(traces), 'output': str(output.relative_to(ROOT))}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-embeddings', action='store_true')
    args = parser.parse_args()
    asyncio.run(seed(args.live_embeddings))
