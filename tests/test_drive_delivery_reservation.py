"""A lost Drive upload response reuses a persisted create ID after its lease."""
from datetime import datetime, timezone
import pytest


def reserve(store, worker='first', **kw):
    return store.reserve_side_effect(execution_id='release-1', work_item_id='file-1',
        effect_type='drive.publish', destination='google:me:release-1:a.pdf',
        content_digest='a'*64, worker_id=worker, **kw)


def test_planned_provider_id_is_immutable_and_survives_reclaim(isolated_store, monkeypatch):
    store = isolated_store
    monkeypatch.setattr(store, '_now', lambda: '2026-09-11T01:00:00+00:00')
    first = reserve(store, lease_seconds=60)
    args = first['effect_id'], first['reservation_token']
    assert store.prepare_side_effect_provider_id(*args, 'google-file-1') == 'google-file-1'
    assert store.prepare_side_effect_provider_id(*args, 'google-file-2') == 'google-file-1'
    monkeypatch.setattr(store, '_now', lambda: '2026-09-11T01:02:00+00:00')
    with pytest.raises(RuntimeError, match='stale'):
        store.prepare_side_effect_provider_id(*args, 'expired-worker')
    next_attempt = reserve(store, worker='successor')
    assert next_attempt['receipt']['planned_provider_id'] == 'google-file-1'
    assert store.prepare_side_effect_provider_id(next_attempt['effect_id'],
        next_attempt['reservation_token'], 'ignored-candidate') == 'google-file-1'
    with pytest.raises(RuntimeError, match='stale'):
        store.prepare_side_effect_provider_id(*args, 'old-worker')


def test_worker_waits_for_reservation_instead_of_exhausting_fast_retries(isolated_store, monkeypatch):
    import handlers  # initialize production registry before isolating additions
    import worker
    monkeypatch.setattr(worker, 'HANDLERS', dict(worker.HANDLERS))
    @worker.handler('reservation-fixture')
    def handle(payload, job):
        raise worker.ReservationRetryError('Delivery reservation is still held', 301)
    start = datetime.now(timezone.utc)
    jid = isolated_store.enqueue_job('reservation-fixture', {})
    worker.JobWorker(isolated_store).run_once()
    job = isolated_store.get_job(jid)
    assert job['status'] == 'queued' and job['attempts'] == 1
    retry = datetime.fromisoformat(job['run_after'])
    assert (retry - start).total_seconds() >= 300


def test_reservation_retry_delay_is_bounded():
    from worker import ReservationRetryError
    assert ReservationRetryError('wait', 10000).retry_after_seconds == 900
    with pytest.raises(ValueError):
        ReservationRetryError('wait', float('nan'))
