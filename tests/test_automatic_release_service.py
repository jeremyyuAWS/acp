"""Synthetic tracked SharePoint records + local jobs; never provider publication."""
import json
from types import SimpleNamespace
import pytest
import automatic_release as flow
import automatic_release_store as persistence

OWNER='release-fixture@example.com'
SID='automatic-fixture'
FILE='deck.pptx'
DIGEST='a'*64


@pytest.fixture
def prepared(isolated_store,monkeypatch):
    import core
    import workspace_roles
    import workspace_rollout
    from routes import scans
    store=isolated_store
    monkeypatch.setattr(core,'store',store)
    monkeypatch.setattr(workspace_rollout,'enforcement_active',lambda:True)
    monkeypatch.setattr(workspace_roles,'access_for_email',lambda *a,**k:{'capabilities':['release.publish']})
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO scan_runs(id,owner_email,source,status,rubric_hash) VALUES(%s,%s,'sharepoint','done','fixture-rubric')",(SID,OWNER))
        store._db.execute(cur,"""INSERT INTO file_records(scan_id,file,engine,status,score,compliant,remediated_at,corrected_sha256,drive_file_id,source_modified,checksum)
            VALUES(%s,%s,'office','analysed',100,1,'2026-09-09T00:00:00Z',%s,'source-item','2026-09-01T00:00:00Z','source-hash')""",(SID,FILE,DIGEST))
        store._db.execute(cur,"INSERT INTO scan_inventory(scan_id,file,drive_file_id,drive_id,source_modified,checksum) VALUES(%s,%s,'source-item','library','2026-09-01T00:00:00Z','source-hash')",(SID,FILE))
    run=store.enqueue_stage_batch(SID,'remediate','remediate_file',[{'owner':OWNER,'scan_id':SID,'file':FILE}],snapshot_id=store.remediation_source_revision(SID),request_fingerprint='fixture')['batch_id']
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE jobs SET status='done' WHERE batch_id=%s",(run,))
    fixture=SimpleNamespace(store=store,run=run,calls=[],mode='queued')
    def publish(sid,request,body):
        fixture.calls.append(body)
        assert sid==SID and request.state.user_email==OWNER
        if fixture.mode=='unknown':raise RuntimeError('synthetic unknown dispatch outcome')
        if fixture.mode=='receipt':
            release=store.ensure_release_execution(SID,OWNER,'sharepoint',1,preferred_folder_name=body['release_folder_name'],parent_folder_id=body['destination']['folder_id'],parent_folder_name=body['destination']['folder_name'])
            store.record_release_document(release['id'],OWNER,dict(file=FILE,status='published',artifact_digest='sha256:'+DIGEST))
            return {'published':[dict(file=FILE,status='published',artifact_digest='sha256:'+DIGEST)]}
        batch='fixture-publish-batch'
        store.enqueue_job('publish_file',{'owner':OWNER,'scan_id':SID,'file':FILE,'artifact_digest':'sha256:'+DIGEST, 'automatic_release_id':body.get('automatic_release_id')},scan_id=SID,batch_id=batch)
        return {'batch_id':batch,'published':[{'file':FILE,'status':'queued'}]}
    monkeypatch.setattr(scans,'publish_files',publish)
    return fixture


def authorize(f):
    destination=flow.preview(f.store,SID,OWNER,[FILE])['destination']
    return flow.authorize(f.store,SID,OWNER,f.run,[FILE],destination,'request-one')


def tick(f,row):
    flow.advance(f.store,{'authorization_id':row['id'],'owner':OWNER,'revision':row['progress']['_tick_revision']},{})
    return persistence.get(f.store,row['id'],OWNER)


def count_jobs(f):
    with f.store._db.cursor() as cur:
        f.store._db.execute(cur,'SELECT COUNT(*) AS n FROM jobs')
        return f.store._db.fetchone(cur)['n']


def test_preview_is_read_only_and_owner_scoped(prepared):
    before=count_jobs(prepared)
    preview=flow.preview(prepared.store,SID,OWNER,[FILE])
    assert preview['available'] is True,preview
    assert preview['authorization'] is None
    assert count_jobs(prepared)==before
    assert flow.preview(prepared.store,SID,'other',[FILE])['available'] is False
    assert not prepared.calls


def test_exact_post_replay_stop_and_conflicting_permission(prepared):
    row=authorize(prepared);count=count_jobs(prepared)
    assert authorize(prepared)==row
    assert count_jobs(prepared)==count
    for files,destination in [(['different.pptx'],row['intent']['destination']),([FILE],{**row['intent']['destination'],'folder_id':'library/other'})]:
        with pytest.raises(ValueError):flow.authorize(prepared.store,SID,OWNER,prepared.run,files,destination,'request-one')
    stopped=persistence.stop(prepared.store,row['id'],OWNER)
    assert authorize(prepared)==stopped
    assert count_jobs(prepared)==count


def test_durable_tick_survives_browser_close_and_queues_exact_artifact(prepared):
    row=authorize(prepared)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT payload FROM jobs WHERE type='release_continue'")
        payload=json.loads(prepared.store._db.fetchone(cur)['payload'])
    flow.advance(prepared.store,payload,{})
    assert prepared.calls[0]['expected_artifacts']=={FILE:DIGEST}
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT payload FROM jobs WHERE type='publish_file'")
        queued=json.loads(prepared.store._db.fetchone(cur)['payload'])
    assert queued['automatic_release_id']==row['id']
    # Replaying the same scheduled job cannot queue a second publication.
    flow.advance(prepared.store,payload,{})
    assert len(prepared.calls)==1


def test_pending_review_does_not_release_or_approve(prepared):
    row=authorize(prepared)
    item=prepared.store.enqueue_proposals(SID,FILE,'2.4.6',[dict(locator='slide 1',proposed_value='A useful title',source='fixture')])
    result=tick(prepared,row)
    assert not prepared.calls
    assert prepared.store.get_hitl_item(item)['status']=='pending'
    assert flow.public(result)['progress']['blocked']==1


@pytest.mark.parametrize('change',['source','run','destination','grants'])
def test_changed_authority_blocks_publication(prepared,monkeypatch,change):
    row=authorize(prepared)
    if change=='grants':
        import workspace_roles
        monkeypatch.setattr(workspace_roles,'access_for_email',lambda *a,**k:{'capabilities':[]})
    elif change=='destination':
        prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',1,preferred_folder_name='Changed',parent_folder_id='library/other')
    else:
        with prepared.store._db.cursor() as cur:
            if change=='source':prepared.store._db.execute(cur,"UPDATE file_records SET source_modified='changed' WHERE scan_id=%s",(SID,))
            else:prepared.store._db.execute(cur,'UPDATE stage_executions SET is_current=0 WHERE execution_id=%s',(prepared.run,))
    result=tick(prepared,row)
    assert not prepared.calls
    assert flow.public(result)['progress']['blocked']==1


def test_stopped_queued_publish_never_calls_provider_callback(prepared):
    from worker import FatalJobError
    row=authorize(prepared)
    flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    persistence.stop(prepared.store,row['id'],OWNER)
    with pytest.raises(FatalJobError):
        flow.publish_job(prepared.store,dict(automatic_release_id=row['id'],owner=OWNER,scan_id=SID,file=FILE,artifact_digest='sha256:'+DIGEST),{},lambda *a:pytest.fail('stop must block callback'))


def test_admitted_before_stop_may_finish_without_reactivation(prepared):
    row=authorize(prepared)
    flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    def admitted(payload,job):
        stopped=persistence.stop(prepared.store,row['id'],OWNER)
        assert stopped['status']=='stopped'
        return 'in-flight callback completed'
    assert flow.publish_job(prepared.store,dict(automatic_release_id=row['id'],owner=OWNER,scan_id=SID,file=FILE,artifact_digest='sha256:'+DIGEST),{},admitted)=='in-flight callback completed'
    assert persistence.get(prepared.store,row['id'],OWNER)['status']=='stopped'


def test_receipt_recovers_delivery_and_unknown_dispatch_is_not_repeated(prepared):
    row=authorize(prepared);prepared.mode='unknown'
    failed=tick(prepared,row)
    tick(prepared,failed)
    assert len(prepared.calls)==1
    release=prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',1,preferred_folder_name=row['intent']['release_folder_name'],parent_folder_id=row['intent']['destination']['folder_id'])
    prepared.store.record_release_document(release['id'],OWNER,dict(file=FILE,status='published',artifact_digest='sha256:'+DIGEST))
    public=flow.public(persistence.get(prepared.store,row['id'],OWNER),prepared.store)
    assert public['progress']['published']==1
    assert public['file_progress'][FILE]['receipt']['artifact_digest']=='sha256:'+DIGEST


def test_successful_exact_receipt_completes_run(prepared):
    row=authorize(prepared);prepared.mode='receipt'
    result=tick(prepared,row)
    assert result['status']=='completed'
    assert flow.public(result,prepared.store)['progress']['published']==1
    assert len(prepared.calls)==1


def test_concurrent_duplicate_ticks_admit_one_delivery(prepared,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    row=authorize(prepared)
    barrier=threading.Barrier(2)
    original=flow.publish_admission
    def simultaneous(*args,**kwargs):
        barrier.wait(timeout=5)
        return original(*args,**kwargs)
    monkeypatch.setattr(flow,'publish_admission',simultaneous)
    def advance(_):
        try:
            return tick(prepared,row)
        except ValueError:
            return None  # A losing CAS worker can defer to the durable winner.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(advance,range(2)))
    assert len(prepared.calls)==1
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT COUNT(*) AS n FROM jobs WHERE type='release_continue'")
        assert prepared.store._db.fetchone(cur)['n']==2  # original + one successor


@pytest.mark.parametrize('blocker',['missing_digest','unverified','unfinished_job','assessment_changed'])
def test_incomplete_or_changed_readiness_never_dispatches(prepared,blocker):
    row=authorize(prepared)
    with prepared.store._db.cursor() as cur:
        if blocker=='missing_digest':prepared.store._db.execute(cur,'UPDATE file_records SET corrected_sha256=NULL WHERE scan_id=%s',(SID,))
        elif blocker=='unverified':prepared.store._db.execute(cur,'UPDATE file_records SET compliant=0 WHERE scan_id=%s',(SID,))
        elif blocker=='unfinished_job':prepared.store._db.execute(cur,"UPDATE jobs SET status='queued' WHERE batch_id=%s",(prepared.run,))
        else:prepared.store._db.execute(cur,"UPDATE scan_runs SET rubric_hash='new-assessment' WHERE id=%s",(SID,))
    result=tick(prepared,row)
    assert not prepared.calls
    assert flow.public(result)['progress']['blocked']==1


def test_frozen_artifact_does_not_dispatch_new_version_or_accept_wrong_receipt(prepared):
    row=authorize(prepared)
    queued=tick(prepared,row)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s',('b'*64,SID))
    release=prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',1,preferred_folder_name=row['intent']['release_folder_name'],parent_folder_id=row['intent']['destination']['folder_id'])
    prepared.store.record_release_document(release['id'],OWNER,dict(file=FILE,status='published',artifact_digest='sha256:'+'b'*64))
    result=tick(prepared,queued)
    assert len(prepared.calls)==1
    assert flow.public(result,prepared.store)['progress']['published']==0
    assert result['progress']['files'][FILE]['artifact_digest']==DIGEST


def test_late_exact_receipt_visible_after_stop_without_new_work(prepared):
    row=authorize(prepared)
    flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    stopped=persistence.stop(prepared.store,row['id'],OWNER)
    before=count_jobs(prepared)
    release=prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',1,preferred_folder_name=row['intent']['release_folder_name'],parent_folder_id=row['intent']['destination']['folder_id'])
    prepared.store.record_release_document(release['id'],OWNER,dict(file=FILE,status='published',artifact_digest='sha256:'+DIGEST))
    status=flow.public(stopped,prepared.store)
    assert status['status']=='stopped' and status['progress']['published']==1
    assert persistence.get(prepared.store,row['id'],OWNER)==stopped
    assert count_jobs(prepared)==before


def test_expired_request_replay_does_not_extend_authorization(prepared,monkeypatch):
    from datetime import datetime,timedelta
    row=authorize(prepared)
    class Later(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime.now(tz)+timedelta(days=2)
    monkeypatch.setattr(flow,'datetime',Later)
    assert authorize(prepared)==row
    final=tick(prepared,row)
    assert final['status']=='failed'
    assert not prepared.calls
    assert authorize(prepared)==final


@pytest.mark.parametrize('files',[[],[FILE,FILE],['x']*501])
def test_invalid_authorization_scope_does_not_schedule(prepared,files):
    before=count_jobs(prepared)
    with pytest.raises(ValueError):
        flow.authorize(prepared.store,SID,OWNER,prepared.run,files,dict(provider='sharepoint',folder_id='library/root',folder_name='Source library root'),'new-request')
    assert count_jobs(prepared)==before
