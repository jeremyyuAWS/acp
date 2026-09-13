"""The job ID returned by a durable stage is pollable before Redis progress exists."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_release_store import _scan


@pytest.fixture
def durable_poll(isolated_store, monkeypatch):
    import core
    from routes import scans
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(core, 'get_job_state', lambda job_id, **kwargs: None)
    app = FastAPI()

    @app.middleware('http')
    async def owner(request, call_next):
        request.state.user_email = request.headers.get('x-test-owner', 'owner@example.com')
        return await call_next(request)

    app.include_router(scans.router)
    _scan(isolated_store, 'durable-scan', 'owner@example.com')
    jid = isolated_store.enqueue_job('assess_trace', {'scan_id': 'durable-scan',
        'access_token': 'PRIVATE_TOKEN_SENTINEL'}, scan_id='durable-scan')
    return isolated_store, TestClient(app), jid


@pytest.mark.parametrize('status,public,phase,done', [
    ('queued', 'queued', 'queued', False), ('running', 'running', 'running', False),
    ('done', 'done', 'complete', True), ('dead', 'failed', 'error', True),
    ('cancelled', 'cancelled', 'cancelled', True),
])
def test_durable_only_stage_job_is_pollable_without_exposing_private_data(durable_poll, status, public, phase, done):
    store, client, jid = durable_poll
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE jobs SET status=%s,last_error=%s WHERE id=%s',
                          (status, 'PRIVATE_ERROR_SENTINEL', jid))
    response = client.get(f'/scans/jobs/{jid}')
    assert response.status_code == 200
    body = response.json()
    assert (body['status'], body['phase'], body['done']) == (public, phase, done)
    assert body['scan_id'] == 'durable-scan'
    assert 'PRIVATE' not in json.dumps(body)
    assert 'payload' not in body
    assert bool(body['error']) == (status == 'dead')


def test_foreign_owner_and_unknown_job_are_both_not_found(durable_poll):
    _, client, jid = durable_poll
    assert client.get(f'/scans/jobs/{jid}', headers={'x-test-owner': 'foreign@example.com'}).status_code == 404
    assert client.get('/scans/jobs/not-a-job').status_code == 404


def test_scanless_job_uses_durable_payload_owner_and_fails_closed(durable_poll):
    store, client, _ = durable_poll
    mine = store.enqueue_job('assess_trace', {'user': 'owner@example.com'})
    theirs = store.enqueue_job('assess_trace', {'user': 'foreign@example.com'})
    unknown = store.enqueue_job('assess_trace', {})
    assert client.get(f'/scans/jobs/{mine}').status_code == 200
    assert client.get(f'/scans/jobs/{theirs}').status_code == 404
    assert client.get(f'/scans/jobs/{unknown}').status_code == 404


@pytest.mark.parametrize('cached', [
    {'status': 'running', 'phase': 'retrying', 'done': False},
    {'state_source': 'durable_queue', 'phase': 'complete', 'done': True},
])
def test_durable_done_overrides_live_cache_and_missing_status(durable_poll, monkeypatch, cached):
    import core
    store, client, jid = durable_poll
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE jobs SET status=%s WHERE id=%s', ('done', jid))
    progress = {**cached, 'scan_id': 'durable-scan', 'seq': 7, 'files_processed': 12,
                'payload': {'token': 'PRIVATE'}, 'last_error': 'PRIVATE'}
    monkeypatch.setattr(core, 'get_job_state', lambda _, **kwargs: progress)
    body = client.get(f'/scans/jobs/{jid}').json()
    assert (body['status'], body['phase'], body['done']) == ('done', 'complete', True)
    assert body['seq'] == 7 and body['files_processed'] == 12
    assert 'PRIVATE' not in json.dumps(body)


def test_cache_identity_never_authorizes_or_leaks_another_scan(durable_poll, monkeypatch):
    import core
    store, client, jid = durable_poll
    _scan(store, 'foreign-scan', 'foreign@example.com')
    monkeypatch.setattr(core, 'get_job_state', lambda _, **kwargs: {
        'scan_id': 'foreign-scan', 'user': 'foreign@example.com', 'files': ['PRIVATE_FOREIGN_FILE']})
    response = client.get(f'/scans/jobs/{jid}')
    assert response.status_code == 200
    assert 'PRIVATE' not in response.text
    assert client.get(f'/scans/jobs/{jid}', headers={'x-test-owner': 'foreign@example.com'}).status_code == 404


def test_scanless_cache_owner_cannot_override_durable_owner(durable_poll, monkeypatch):
    import core
    store, client, _ = durable_poll
    jid = store.enqueue_job('remediate_batch', {'user': 'foreign@example.com'})
    monkeypatch.setattr(core, 'get_job_state', lambda _, **kwargs: {'user': 'owner@example.com', 'done': False})
    assert client.get(f'/scans/jobs/{jid}').status_code == 404


def test_sse_refreshes_durable_completion_even_when_sequence_stays_unchanged(durable_poll, monkeypatch):
    import asyncio
    import core
    from routes import scans
    from starlette.requests import Request
    store, _, jid = durable_poll
    reads = []
    original = store.get_job
    def durable(job_id):
        row = original(job_id)
        reads.append(asyncio_clock[0])
        row['status'] = 'running' if len(reads) == 1 else 'done'
        return row
    asyncio_clock = [0.0]
    monkeypatch.setattr(store, 'get_job', durable)
    monkeypatch.setattr(core, 'get_job_state', lambda _, **kwargs: {
        'scan_id': 'durable-scan', 'seq': 3, 'status': 'running', 'done': False,
        'phase': 'remediating', 'files_processed': 9})
    request = Request({'type': 'http', 'headers': [], 'state': {'user_email': 'owner@example.com'}})
    async def exercise():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, 'time', lambda: asyncio_clock[0])
        real_sleep = asyncio.sleep
        async def advance(seconds):
            asyncio_clock[0] += seconds
            await real_sleep(0)
        monkeypatch.setattr(asyncio, 'sleep', advance)
        response = await scans.stream_job_state(jid, request)
        frames = [frame async for frame in response.body_iterator]
        return frames
    frames = asyncio.run(exercise())
    assert reads == [0.0, 1.0]
    assert len(frames) == 3
    assert '"status": "running"' in frames[0]
    assert '"status": "done"' in frames[1] and '"files_processed": 9' in frames[1]
    assert frames[2].startswith('event: done')


def test_legacy_stale_progress_without_durable_row_still_closes_without_extra_sql(durable_poll, monkeypatch):
    import core
    from routes import scans
    sql_reads = []
    monkeypatch.setattr(core.store, 'get_job', lambda _: sql_reads.append(True))
    monkeypatch.setattr(core, 'get_job_state', lambda _, **kwargs: {
        'scan_id': 'durable-scan', 'phase': 'running', 'done': False,
        'updated_at': '2000-01-01T00:00:00+00:00'})
    monkeypatch.setattr(core, '_job_is_stale', lambda state: True)
    state = scans._scan_job_state('legacy', durable=None)
    assert state['done'] is True and state['phase'] == 'error'
    assert 'interrupted' in state['error']
    assert sql_reads == []
