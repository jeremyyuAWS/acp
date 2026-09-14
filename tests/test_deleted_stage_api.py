"""Erased scans keep audit history, but cannot expose actionable stage screens."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from routes import stage_executions as routes


@pytest.fixture
def execution_store(monkeypatch):
    execution = {'execution_id': 'old-run', 'scan_id': 'erased-scan',
                 'owner_email': 'owner@example.com', 'is_current': 1}
    store = SimpleNamespace(
        get_stage_execution=lambda _, owner: execution if owner == execution['owner_email'] else None,
        current_stage_execution=lambda *_args, owner: execution if owner == execution['owner_email'] else None,
        get_scan_head=lambda _sid, owner: None,
    )
    monkeypatch.setattr(routes.core, 'store', store)
    return store, execution


@pytest.mark.parametrize('view', ['detail', 'current', 'events', 'snapshot', 'queue', 'resume'])
def test_deleted_scan_stage_is_not_actionable(execution_store, view):
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner@example.com'))
    with pytest.raises(HTTPException) as error:
        if view == 'current':
            routes.current_execution('workflow', 'remediate', request)
        elif view == 'queue':
            routes.execution_queue('old-run', request, 'needs_review')
        elif view == 'resume':
            routes.resume_execution('old-run', routes.RevisionMutation(expected_revision=1), request)
        else:
            getattr(routes, 'execution_' + view)('old-run', request)
    assert error.value.status_code == 404


def test_live_scan_historical_execution_remains_readable(execution_store):
    store, execution = execution_store
    execution['is_current'] = 0
    store.get_scan_head = lambda sid, owner: {'id': sid}
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner@example.com'))
    assert routes.execution_detail('old-run', request) == execution


def test_foreign_owner_cannot_read_stage(execution_store):
    store, _ = execution_store
    store.get_scan_head = lambda sid, owner: {'id': sid}
    request = SimpleNamespace(state=SimpleNamespace(user_email='other@example.com'))
    with pytest.raises(HTTPException) as error:
        routes.execution_detail('old-run', request)
    assert error.value.status_code == 404
