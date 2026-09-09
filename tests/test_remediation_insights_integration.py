"""Production Store/context/route boundaries for retained remediation insights."""
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from ai_attempt_history import AttemptHistory
from ai_review_chain import _save_review
from ai_run_policy import run_context
from remediation_run_insights import read_insights

TABLES = ('ai_attempt_history', 'ai_attempt_trace_links', 'ai_review_receipts', 'ai_proposal_snapshots')


def managed_run(store, owner='owner', scan='scan'):
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status) VALUES(%s,%s,'done')", (scan, owner))
    result = store.enqueue_stage_batch(scan, 'remediate', 'remediate_file', [{
        'owner': owner, 'scan_id': scan, 'file': 'a.html',
        'remediation_impact_policy': {'ai': 1, 'rule_based': 2, 'ai_budget_usd': '0.10', 'snapshot_id': 'fixture-policy'},
    }], snapshot_id='snapshot', request_fingerprint='fixture')
    return result, store.get_job(result['job_ids'][0])


def retain(store, job, *, value='A flowering tree'):
    with run_context(store, job['payload'], job) as ctx:
        history = AttemptHistory(store._db)
        history.begin(ctx.owner_id, ctx.scan_id, ctx.run_id, 'operation', 'attempt', file=ctx.file,
            input_sha256=sha256(b'source').hexdigest(), model='fixture-model', provider='fixture')
        ctx.ledger.reserve(ctx.owner_id, ctx.run_id, 'attempt', 1000, 'fixture-price')
        ctx.ledger.claim_dispatch(ctx.owner_id, ctx.run_id, 'attempt')
        ctx.ledger.settle(ctx.owner_id, ctx.run_id, 'attempt', 1000)
        history.finish(ctx.owner_id, ctx.scan_id, ctx.run_id, 'attempt', status='drafted',
            result={'text': value, 'model': 'fixture-model', 'provider': 'fixture'})
        call = store.record_ai_call(surface='text', provider='fixture', model='fixture-model',
            zone='fixture', latency_ms=1, ok=True, scan_id=ctx.scan_id, file=ctx.file)
        assert history.bind_trace(ctx.owner_id, ctx.scan_id, ctx.run_id, 'operation', call,
            file=ctx.file, output_sha256=sha256(value.encode()).hexdigest()) == 'attempt'
        item = store.enqueue_proposals(ctx.scan_id, ctx.file, '1.1.1', [{
            'locator': 'image-1', 'before': '', 'proposed_value': value,
            'model': 'fixture-model', 'model_call_id': call, 'rationale': 'Visible content',
        }])
        _save_review(ctx, 'operation', sha256(value.encode()).hexdigest(),
            {'verdict': 'accept', 'reason': 'Human review remains required.', 'steps': []})
    return item


def counts(store, owner):
    result = {}
    with store._db.cursor() as cur:
        for table in TABLES:
            store._db.execute(cur, f'SELECT COUNT(*) AS n FROM {table} WHERE owner_id=%s', (owner,))
            result[table] = store._db.fetchone(cur)['n']
    return result


def test_real_enqueue_captures_exact_context_and_update_keeps_original_version(isolated_store):
    store = isolated_store
    result, job = managed_run(store)
    item = retain(store, job)
    first = read_insights(store, 'owner', 'scan', result['batch_id'])
    assert first['proposals'][0]['item_id'] == item
    assert first['proposals'][0]['attempt_id'] == 'attempt'
    assert first['contribution']['draft'] == 1
    assert first['review_receipts'][0]['review']['verdict'] == 'accept'
    original = first['proposals'][0]['proposal']['proposed_value']
    # The queue's replacement seam also captures an immutable version.
    call = first['proposals'][0]['model_call_id']
    with run_context(store, job['payload'], job):
        assert store.enqueue_proposals('scan', 'a.html', '1.1.1', [{
            'before': '', 'proposed_value': 'An edited description', 'locator': 'image-1',
            'model': 'fixture-model', 'model_call_id': call,
        }]) == item
    values = [row['proposal']['proposed_value'] for row in read_insights(store, 'owner', 'scan', result['batch_id'])['proposals']]
    assert values == [original, 'An edited description']


def test_enqueue_outside_matching_worker_context_cannot_claim_execution(isolated_store):
    store = isolated_store
    result, job = managed_run(store)
    store.enqueue_proposals('scan', 'a.html', '1.1.1', [{'proposed_value': 'legacy'}])
    with run_context(store, job['payload'], job):
        store.enqueue_proposals('scan', 'different.html', '1.1.1', [{'proposed_value': 'different file'}])
    assert read_insights(store, 'owner', 'scan', result['batch_id'])['proposals'] == []


@pytest.mark.parametrize('erase', ['reset_user_data', 'delete_scan'])
def test_erasure_purges_all_retained_insights_without_touching_another_owner(isolated_store, erase):
    store = isolated_store
    first, job = managed_run(store)
    other, other_job = managed_run(store, owner='other', scan='other-scan')
    retain(store, job); retain(store, other_job)
    assert all(value == 1 for value in counts(store, 'owner').values())
    before_other = counts(store, 'other')
    if erase == 'delete_scan':
        assert store.delete_scan('scan', 'other') is None
        assert all(value == 1 for value in counts(store, 'owner').values())
        assert store.delete_scan('scan', 'owner')['scan_id'] == 'scan'
    else:
        store.reset_user_data('owner')
    assert all(value == 0 for value in counts(store, 'owner').values())
    assert counts(store, 'other') == before_other
    assert read_insights(store, 'other', 'other-scan', other['batch_id'])['proposals']
    # Stage audit identities may remain after erasure, but retained content is gone.
    erased = read_insights(store, 'owner', 'scan', first['batch_id'])
    assert erased['attempts'] == erased['proposals'] == erased['review_receipts'] == []
    assert store.get_scan('scan', owner='owner') is None


def test_insights_route_checks_scan_and_execution_owner_and_disables_caching(isolated_store, monkeypatch):
    import core
    from routes.remediation_waterfall import run_insights
    store = isolated_store
    first, job = managed_run(store); retain(store, job)
    other, _ = managed_run(store, owner='other', scan='other-scan')
    monkeypatch.setattr(core, 'store', store)
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner'))
    response = Response()
    data = run_insights('scan', first['batch_id'], request, response, offset=0, limit=100)
    assert data['batch_id'] == first['batch_id']
    assert response.headers['Cache-Control'] == 'no-store'
    for scan, batch, email in [('scan', first['batch_id'], 'other'),
                               ('other-scan', other['batch_id'], 'owner'),
                               ('scan', other['batch_id'], 'owner')]:
        request = SimpleNamespace(state=SimpleNamespace(user_email=email))
        with pytest.raises(HTTPException) as exc:
            run_insights(scan, batch, request, Response(), offset=0, limit=100)
        assert exc.value.status_code == 404

    store.delete_scan('scan', 'owner')
    with pytest.raises(HTTPException) as exc:
        run_insights('scan', first['batch_id'], SimpleNamespace(state=SimpleNamespace(user_email='owner')), Response(), offset=0, limit=100)
    assert exc.value.status_code == 404
