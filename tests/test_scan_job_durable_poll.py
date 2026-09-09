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
    monkeypatch.setattr(core, 'get_job_state', lambda job_id: None)
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
