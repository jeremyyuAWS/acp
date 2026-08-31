"""Reserved discovery claims bypass content backlog without losing durable ownership."""
import pytest
from worker import JobWorker

def test_reserved_claim_skips_content_backlog(isolated_store):
    s=isolated_store
    content=s.enqueue_job('scan_file', {}, priority=0)
    discovery=s.enqueue_job('scan_discover', {}, priority=100)
    claimed=s.claim_job('discovery-lane',job_types=('scan_discover',))
    assert claimed['id']==discovery
    assert claimed['attempts']==1 and claimed['lease_expires_at']
    assert s.get_job(content)['status']=='queued'
    assert s.claim_job('discovery-lane',job_types=('scan_discover',)) is None
    assert s.claim_job('general')['id']==content

def test_empty_lane_claims_nothing(isolated_store):
    isolated_store.enqueue_job('scan_file', {})
    assert isolated_store.claim_job('closed',job_types=()) is None

@pytest.mark.parametrize('value,size,want',[('1',12,1),('99',2,1),('1',1,0),('-1',12,0),('bad',12,0)])
def test_reservation_preserves_general_capacity(monkeypatch,value,size,want):
    import core
    monkeypatch.setenv('ACP_DISCOVERY_RESERVED_WORKERS',value)
    assert core._discovery_reservation(size)==want

def test_reserved_worker_does_not_execute_content(isolated_store):
    jid=isolated_store.enqueue_job('scan_file',{})
    assert not JobWorker(isolated_store,job_types=('scan_discover',)).run_once()
    assert isolated_store.get_job(jid)['status']=='queued'
