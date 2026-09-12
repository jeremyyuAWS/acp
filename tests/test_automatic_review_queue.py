"""Automatic checks are admitted pipeline work, never credited approval or resolution."""
from types import SimpleNamespace
import pytest
from test_ai_standing_approval import seed, proposal, OWNER, SID, FILE
from ai_run_policy import run_context
from ai_run_approval_override import read, save
from automatic_review_queue import annotate


def setup_queue(store, monkeypatch):
    job = seed(store, monkeypatch, enabled=False)
    with run_context(store, job['payload'], job) as ctx:
        item = store.enqueue_proposals(SID, FILE, '2.4.6', [proposal(store)])
        setting = read(store, OWNER, SID, ctx.run_id)
        save(store, OWNER, SID, ctx.run_id, True, 0, setting['source_revision'])
    return item, ctx.run_id


def test_owner_route_projects_exact_pending_checks_without_mutation(isolated_store, monkeypatch):
    from routes.hitl import hitl_list
    import ai_standing_approval
    item, run_id = setup_queue(isolated_store, monkeypatch)
    monkeypatch.setattr(ai_standing_approval, '_source', lambda *a, **k: pytest.fail('Polling must not read provider or blob bytes'))
    rows = hitl_list(SimpleNamespace(state=SimpleNamespace(user_email=OWNER)), scan_id=SID)
    row = next(row for row in rows if row['id'] == item)
    assert row['auto_approval_status'] == 'checking'
    assert row['auto_approval_run_id'] == run_id
    assert row['status'] == 'pending' and not row.get('applied') and not row.get('validated')
    assert isolated_store.get_hitl_item(item)['status'] == 'pending'
    assert annotate(isolated_store, rows, 'other@example.test')[0].get('auto_approval_status') is None
    assert annotate(isolated_store, [isolated_store.get_hitl_item(item)], 'other@example.test')[0].get('auto_approval_status') is None


@pytest.mark.parametrize('failure', ['off', 'finished', 'source', 'proposal', 'manual'])
def test_unadmitted_stale_or_manual_rows_remain_human_input(isolated_store, monkeypatch, failure):
    item, run_id = setup_queue(isolated_store, monkeypatch)
    row = isolated_store.get_hitl_item(item)
    if failure == 'off':
        state = read(isolated_store, OWNER, SID, run_id)
        save(isolated_store, OWNER, SID, run_id, False, 1, state['source_revision'])
    elif failure == 'finished':
        with isolated_store._db.cursor() as cur:
            isolated_store._db.execute(cur, "UPDATE jobs SET status='done' WHERE scan_id=%s AND type='apply_approved_values'", (SID,))
    elif failure == 'source':
        monkeypatch.setattr(isolated_store, 'remediation_source_revision', lambda sid: 'changed')
    elif failure == 'proposal':
        row['proposals'][0]['proposed_value'] = 'not the recorded exact output'
    else:
        row['proposals'] = []
    projected = annotate(isolated_store, [row], OWNER)[0]
    assert projected.get('auto_approval_status') is None
    assert projected['status'] == 'pending'
