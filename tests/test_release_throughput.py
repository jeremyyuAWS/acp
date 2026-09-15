"""Offline completion events and exact SharePoint queue admission."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
import automatic_release as flow
import automatic_release_store as persistence
from test_automatic_release_service import prepared, authorize, tick, OWNER, SID, FILE, DIGEST


def add_file(f, name):
    with f.store._db.cursor() as cur:
        f.store._db.execute(cur, "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,remediated_at,corrected_sha256,drive_file_id,source_modified,checksum) SELECT scan_id,%s,engine,status,score,compliant,remediated_at,corrected_sha256,drive_file_id,source_modified,checksum FROM file_records WHERE scan_id=%s AND file=%s", (name,SID,FILE))
        f.store._db.execute(cur, "INSERT INTO scan_inventory(scan_id,file,drive_file_id,drive_id,source_modified,checksum) SELECT scan_id,%s,drive_file_id,drive_id,source_modified,checksum FROM scan_inventory WHERE scan_id=%s AND file=%s", (name,SID,FILE))
        f.store._db.execute(cur, "INSERT INTO stage_work_items(work_item_id,execution_id,input_id,job_id,state,revision,attempt,created_at,updated_at) SELECT %s,execution_id,%s,job_id,state,revision,attempt,created_at,updated_at FROM stage_work_items WHERE execution_id=%s AND input_id=%s", ('fixture-'+name,name,f.run,FILE))
        f.store._db.execute(cur, 'UPDATE stage_executions SET input_snapshot_id=%s WHERE execution_id=%s', (f.store.remediation_source_revision(SID),f.run))


def authorize_many(f, files):
    destination=flow.preview(f.store,SID,OWNER,files)['destination']
    with f.store._db.cursor() as cur:
        f.store._db.execute(cur,'UPDATE stage_executions SET input_snapshot_id=%s WHERE execution_id=%s', (f.store.remediation_source_revision(SID),f.run))
    return flow.authorize(f.store,SID,OWNER,f.run,files,destination,'request-many')


def queue(f,row,release,file):
    return f.store.enqueue_automatic_sharepoint_release(SID,[dict(scan_id=SID,owner=OWNER,
        automatic_release_id=row['id'],release_id=release['id'],file=file,
        artifact_digest='sha256:'+DIGEST,remediated_at='2026-09-09T00:00:00Z')],
        snapshot_id='fixture',request_fingerprint='fixture-'+file)


def test_duplicate_completion_events_promote_one_tick_without_new_authority(prepared):
    row=authorize(prepared)
    row=persistence.save(prepared.store,row,status='waiting',progress=row['progress'],schedule=True,delay=300)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT id FROM jobs WHERE type='release_continue'")
        before=[j['id'] for j in prepared.store._db.fetchall(cur)]
    persistence.wake(prepared.store,SID)
    persistence.wake(prepared.store,SID)
    assert persistence.get(prepared.store,row['id'],OWNER)==row
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT id,payload,run_after FROM jobs WHERE type='release_continue'")
        after=prepared.store._db.fetchall(cur)
    assert [j['id'] for j in after]==before
    current=next(j for j in after if json.loads(j['payload'])['revision']==row['progress']['_tick_revision'])
    assert datetime.fromisoformat(current['run_after'])<=datetime.now(timezone.utc)
    persistence.stop(prepared.store,row['id'],OWNER)
    persistence.wake(prepared.store,SID)
    assert persistence.get(prepared.store,row['id'],OWNER)['status']=='stopped'


def test_event_during_running_tick_requests_immediate_recovery(prepared):
    row=authorize(prepared)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"UPDATE jobs SET status='running' WHERE type='release_continue'")
    persistence.wake(prepared.store,SID)
    row=persistence.get(prepared.store,row['id'],OWNER)
    assert row['progress']['_wake_requested']
    row=tick(prepared,row)
    assert '_wake_requested' not in row['progress']
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT run_after FROM jobs WHERE type='release_continue' AND status='queued'")
        assert datetime.fromisoformat(prepared.store._db.fetchone(cur)['run_after'])<=datetime.now(timezone.utc)


def test_atomic_admissions_allow_only_two_even_before_queue_creation(prepared):
    names=[FILE,'second.pptx','third.pptx']
    for name in names[1:]:add_file(prepared,name)
    row=authorize_many(prepared,names)
    def admit(name):
        try:
            flow.publish_admission(prepared.store,row['id'],OWNER,SID,name,DIGEST)
            return 'admitted'
        except flow.DeliveryCapacityFull:return 'full'
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(admit,names))==['admitted','admitted','full']


def test_sharepoint_append_preserves_same_execution_and_job_identity(prepared):
    add_file(prepared,'second.pptx')
    row=authorize_many(prepared,[FILE,'second.pptx'])
    for name in row['intent']['files']:
        row=flow.publish_admission(prepared.store,row['id'],OWNER,SID,name,DIGEST)
    release=prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',2,
        preferred_folder_name=row['intent']['release_folder_name'],parent_folder_id=row['intent']['release_parent_id'])
    first=queue(prepared,row,release,FILE)
    second=queue(prepared,row,release,'second.pptx')
    assert second['batch_id']==first['batch_id']
    assert queue(prepared,row,release,FILE)['job_ids']==first['job_ids']
    execution=prepared.store.get_stage_execution(first['batch_id'],owner=OWNER)
    assert execution['expected_items']==2
    persistence.stop(prepared.store,row['id'],OWNER)
    with pytest.raises(ValueError,match='stopped|active'):
        queue(prepared,row,release,FILE)


def test_sharepoint_rejects_other_intent_and_changed_artifact(prepared):
    row=authorize(prepared)
    row=flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    release=prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',1,
        preferred_folder_name=row['intent']['release_folder_name'],parent_folder_id=row['intent']['release_parent_id'])
    prepared.store.enqueue_stage_batch(SID,'release','publish_file',
        [dict(file=FILE,owner=OWNER,scan_id=SID,release_id=release['id'],artifact_digest='sha256:'+DIGEST)],
        snapshot_id='fixture',request_fingerprint='unrelated')
    with pytest.raises(ValueError,match='different delivery intent'):
        queue(prepared,row,release,FILE)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s',('b'*64,SID))
    with pytest.raises(ValueError):queue(prepared,row,release,FILE)


def test_durable_job_completion_wakes_saved_recovery_tick(prepared):
    row=authorize(prepared)
    row=persistence.save(prepared.store,row,status='waiting',progress=row['progress'],schedule=True,delay=300)
    job_id=prepared.store.enqueue_job('rescore_file',dict(scan_id=SID,owner=OWNER,file=FILE),scan_id=SID)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"UPDATE jobs SET status='running',locked_by='fixture-worker',attempts=1 WHERE id=%s",(job_id,))
    assert prepared.store.complete_job(job_id,worker_id='fixture-worker',attempt=1)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT payload,run_after FROM jobs WHERE type='release_continue'")
        current=next(j for j in prepared.store._db.fetchall(cur) if json.loads(j['payload'])['revision']==row['progress']['_tick_revision'])
    assert datetime.fromisoformat(current['run_after'])<=datetime.now(timezone.utc)
    assert not prepared.store.complete_job(job_id,worker_id='other-worker',attempt=1)


def test_provider_backoff_retains_upload_slot(prepared):
    names=[FILE,'second.pptx','third.pptx']
    for name in names[1:]:add_file(prepared,name)
    row=authorize_many(prepared,names)
    for name in names[:2]:
        row=flow.publish_admission(prepared.store,row['id'],OWNER,SID,name,DIGEST)
        prepared.store.enqueue_job('publish_file',dict(scan_id=SID,owner=OWNER,file=name,
            automatic_release_id=row['id']),scan_id=SID,
            run_after=(datetime.now(timezone.utc)+timedelta(seconds=300)).isoformat())
        persistence.update_file(prepared.store,row['id'],OWNER,name,dict(state='blocked'))
    with pytest.raises(flow.DeliveryCapacityFull):
        flow.publish_admission(prepared.store,row['id'],OWNER,SID,names[2],DIGEST)


def test_concurrent_stop_is_admission_barrier(prepared):
    row=authorize(prepared)
    def admit():
        try:return flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)['status']
        except ValueError:return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        admission=pool.submit(admit)
        stop=pool.submit(persistence.stop,prepared.store,row['id'],OWNER)
        assert admission.result() in {'active','refused'}
        assert stop.result()['status']=='stopped'
    with pytest.raises(ValueError,match='active'):
        flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST,queued=True)


def test_cross_owner_cannot_admit_and_wrong_permission_cannot_append(prepared):
    row=authorize(prepared)
    with pytest.raises(ValueError):
        flow.publish_admission(prepared.store,row['id'],'other-owner',SID,FILE,DIGEST)
    row=flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    release=prepared.store.ensure_release_execution(SID,OWNER,'sharepoint',1,
        preferred_folder_name=row['intent']['release_folder_name'],parent_folder_id=row['intent']['release_parent_id'])
    with pytest.raises(ValueError,match='permission does not match'):
        queue(prepared,{**row,'id':'other-permission'},release,FILE)
