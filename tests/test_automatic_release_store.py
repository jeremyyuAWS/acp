"""Synthetic authorizations and local jobs, never customer publication."""
from concurrent.futures import ThreadPoolExecutor
import threading
import json
import pytest
import automatic_release_store as a
from test_remediation_waterfall_view import seed


@pytest.fixture
def scope(isolated_store):
    return isolated_store, seed(isolated_store)


def create(scope,request='request',intent=None):
    store,run=scope
    return a.create(store,'owner','scan',run,request,{'destination':'fixture'} if intent is None else intent)


def jobs(store):
    with store._db.cursor() as cur:
        store._db.execute(cur,"SELECT * FROM jobs WHERE type='release_continue'")
        return store._db.fetchall(cur)


def test_create_exact_replay_schedules_once(scope):
    store,run=scope
    row=create(scope)
    assert row['status']=='active' and row['revision']==0
    assert create(scope)==row
    assert len(jobs(store))==1
    payload=json.loads(jobs(store)[0]['payload'])
    assert payload==dict(mode='automatic',authorization_id=row['id'],owner='owner',revision=0)
    assert row['progress']['_tick_revision']==0
    assert a.latest(store,'scan','owner',run_id=run)==row
    assert a.latest(store,'scan','owner',run_id='other') is None


def test_conflicting_intent_and_active_request_rejected(scope):
    create(scope)
    with pytest.raises(ValueError,match='immutable'): create(scope,intent={'destination':'changed'})
    with pytest.raises(ValueError,match='already active'): create(scope,request='other')
    assert len(jobs(scope[0]))==1


def test_owner_scope(scope):
    store,run=scope;row=create(scope)
    assert a.get(store,row['id'],'other') is None
    assert a.latest(store,'scan','other') is None
    with pytest.raises(ValueError):a.stop(store,row['id'],'other')
    with pytest.raises(ValueError):a.create(store,'other','scan',run,'r',{})
    with pytest.raises(ValueError):a.create(store,'owner','scan','wrong','r',{})


def test_cas_schedules_once_and_cannot_reactivate_stopped(scope):
    store,run=scope;row=create(scope)
    updated=a.save(store,row,status='waiting',progress={},schedule=True)
    assert updated['revision']==updated['progress']['_tick_revision']==1
    with pytest.raises(ValueError,match='changed'):a.save(store,row,status='waiting',progress={},schedule=True)
    assert len(jobs(store))==2
    stopped=a.stop(store,row['id'],'owner')
    assert stopped['stopped_at'] and stopped['status']=='stopped'
    assert a.stop(store,row['id'],'owner')==stopped
    assert create(scope)==stopped
    with pytest.raises(ValueError):a.save(store,stopped,status='active',progress={},schedule=True)
    assert a.update_file(store,row['id'],'owner','a',{'state':'done'})==stopped
    assert len(jobs(store))==2


def test_schedule_failure_rolls_back_state_and_creation(scope,monkeypatch):
    store,run=scope
    original=store.enqueue_job
    monkeypatch.setattr(store,'enqueue_job',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('fixture failure')))
    with pytest.raises(RuntimeError):create(scope)
    assert a.latest(store,'scan','owner') is None
    monkeypatch.setattr(store,'enqueue_job',original)
    row=create(scope)
    monkeypatch.setattr(store,'enqueue_job',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('fixture failure')))
    with pytest.raises(RuntimeError):a.save(store,row,status='waiting',progress={'test':1},schedule=True)
    assert a.get(store,row['id'],'owner')==row


def test_file_updates_preserve_pending_tick_and_other_files(scope):
    store,run=scope;row=create(scope)
    one=a.update_file(store,row['id'],'owner','a',{'state':'queued','digest':'one'})
    two=a.update_file(store,row['id'],'owner','b',{'state':'done'})
    three=a.update_file(store,row['id'],'owner','a',{'state':'done'})
    assert three['revision']==3
    assert three['progress']['_tick_revision']==0
    assert three['progress']['files']=={'a':{'state':'done','digest':'one'},'b':{'state':'done'}}
    assert len(jobs(store))==1


def test_concurrent_file_updates_do_not_lose_progress(scope):
    store,run=scope;row=create(scope)
    barrier=threading.Barrier(2)
    def work(file):
        barrier.wait()
        return a.update_file(store,row['id'],'owner',file,{'state':'done'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(work,['a','b']))
    final=a.get(store,row['id'],'owner')
    assert final['revision']==2
    assert set(final['progress']['files'])=={'a','b'}


def test_concurrent_duplicate_creation_schedules_once(scope):
    barrier=threading.Barrier(2)
    def work(_):
        barrier.wait()
        return create(scope)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(work,range(2)))
    assert rows[0]['id']==rows[1]['id']
    assert len(jobs(scope[0]))==1


def test_stop_racing_file_update_cannot_be_undone(scope):
    store,run=scope;row=create(scope)
    barrier=threading.Barrier(2)
    def stop():
        barrier.wait();return a.stop(store,row['id'],'owner')
    def update():
        barrier.wait();return a.update_file(store,row['id'],'owner','a',{'state':'done'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(stop),pool.submit(update)]
        [f.result() for f in futures]
    assert a.get(store,row['id'],'owner')['status']=='stopped'


def test_delete_scan_erases_authorization(scope):
    store,run=scope;row=create(scope)
    store.delete_scan('scan','owner')
    assert a.get(store,row['id'],'owner') is None


def test_schema_50_is_pinned():
    import store
    assert store._PgAdapter._SCHEMA_VERSION==50
    assert store._PgAdapter._schema_checksum()==store._PgAdapter._SCHEMA_CHECKSUM_AT_VERSION


def test_two_workers_cas_only_one_successor(scope):
    store,run=scope;row=create(scope)
    barrier=threading.Barrier(2)
    def save(_):
        barrier.wait()
        try:
            return a.save(store,row,status='waiting',progress={},schedule=True)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(save,range(2)))
    assert sum(r is not None for r in results)==1
    assert len(jobs(store))==2


def test_stopped_request_cannot_authorize_again_but_new_request_can(scope):
    store,run=scope;row=create(scope)
    a.stop(store,row['id'],'owner')
    replacement=create(scope,request='new-explicit-authorization')
    assert replacement['id']!=row['id']
    assert replacement['status']=='active'
    assert create(scope)['status']=='stopped'
    assert len(jobs(store))==2
