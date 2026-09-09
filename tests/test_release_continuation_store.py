"""Persistent authorization survives process reloads and cannot broaden on retry."""
import pytest
import release_continuation_store as intents
from test_release_store import _scan


def test_intent_owner_scope_idempotent_creation_and_atomic_successor(isolated_store):
    store = isolated_store
    owner = 'owner@example.com'
    _scan(store, 'scan', owner)
    intent = {'files': ['one.pdf'], 'destination': {'folder_id': 'fixed'}, 'proposals': ['v1']}
    first = intents.create(store, owner, 'scan', intent)
    assert intents.create(store, owner, 'scan', intent)['id'] == first['id']
    assert intents.get(store, first['id'], 'foreign@example.com') is None
    with pytest.raises(ValueError, match='scan not found'):
        intents.create(store, 'foreign@example.com', 'scan', intent)
    assert intents.create(store, owner, 'scan', {**intent, 'proposals': ['v2']})['id'] != first['id']
    saved = intents.save(store, first, status='waiting', progress={'one.pdf': {'state': 'applying'}}, schedule=True)
    assert saved['revision'] == 1
    with pytest.raises(ValueError, match='changed'):
        intents.save(store, first, status='waiting', progress={}, schedule=True)
    jobs = [j for j in store.list_jobs(owner=owner) if j['type'] == 'release_continue']
    assert len(jobs) == 1
    assert intents.latest(store, 'scan', owner)['id'] == first['id']
    assert intents.latest(store, 'scan', 'foreign@example.com') is None
    # A new module/process read relies only on the durable store, not a browser/session map.
    assert intents.get(store, first['id'], owner)['progress']['one.pdf']['state'] == 'applying'


def test_failed_successor_insert_rolls_back_progress(isolated_store, monkeypatch):
    store = isolated_store
    owner = 'owner@example.com'
    _scan(store, 'scan', owner)
    row = intents.create(store, owner, 'scan', {'files': ['one.pdf']})
    def fail(*args, **kwargs):
        raise RuntimeError('queue unavailable')
    monkeypatch.setattr(store, 'enqueue_job', fail)
    with pytest.raises(RuntimeError, match='queue unavailable'):
        intents.save(store, row, status='waiting', progress={'started': True}, schedule=True)
    current = intents.get(store, row['id'], owner)
    assert current['status'] == 'draft' and current['revision'] == 0
