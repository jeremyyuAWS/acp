"""Legacy producers retain immutable versions without acquiring AI permissions."""
import pytest
from ai_run_policy import run_context
from remediation_run_insights import proposal_context
from test_ai_run_policy import seed, enqueue


def produce(store, job, payload=None):
    with run_context(store, job['payload'], job) as managed:
        assert managed is None
        with proposal_context(store, payload or job['payload'], job) as lineage:
            item = store.enqueue_proposals('scan', 'a.html', '1.1.1',
                [{'locator': 'image:1', 'before': '', 'proposed_value': 'A tree'}], finding_count=1)
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT proposal_snapshot_ids FROM hitl_queue WHERE id=%s', (item,))
        return lineage, store._db.fetchone(cur)['proposal_snapshot_ids']


def test_accepted_legacy_producer_retains_versions_without_budget(isolated_store):
    seed(isolated_store)
    batch = enqueue(isolated_store, amount=None)
    job = isolated_store.get_job(batch['job_ids'][0])
    lineage, snapshots = produce(isolated_store, job)
    assert lineage['run_id'] == batch['batch_id']
    assert snapshots and snapshots != '[]'


@pytest.mark.parametrize('field,value', [('owner', 'other'), ('file', 'other.html'), ('scan_id', 'other')])
def test_forged_producer_cannot_capture_versions(isolated_store, field, value):
    seed(isolated_store)
    batch = enqueue(isolated_store, amount=None)
    job = isolated_store.get_job(batch['job_ids'][0])
    lineage, snapshots = produce(isolated_store, job, {**job['payload'], field: value})
    assert lineage is None
    assert not snapshots or snapshots == '[]'


def test_cancelled_producer_cannot_capture_versions(isolated_store):
    seed(isolated_store)
    batch = enqueue(isolated_store, amount=None)
    job = isolated_store.get_job(batch['job_ids'][0])
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'UPDATE stage_executions SET cancel_requested_at=%s WHERE execution_id=%s', ('now', batch['batch_id']))
    lineage, snapshots = produce(isolated_store, job)
    assert lineage is None
    assert not snapshots or snapshots == '[]'


def test_replacement_outside_producer_clears_old_snapshot_ids(isolated_store):
    seed(isolated_store)
    batch = enqueue(isolated_store, amount=None)
    job = isolated_store.get_job(batch['job_ids'][0])
    assert produce(isolated_store, job)[1] != '[]'
    item = isolated_store.enqueue_proposals('scan', 'a.html', '1.1.1',
        [{'locator': 'image:1', 'before': '', 'proposed_value': 'A different tree'}], finding_count=1)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'SELECT proposal_snapshot_ids FROM hitl_queue WHERE id=%s', (item,))
        assert isolated_store._db.fetchone(cur)['proposal_snapshot_ids'] == '[]'
