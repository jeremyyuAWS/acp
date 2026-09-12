import json
import pytest
from test_ai_standing_approval import seed, proposal, apply_jobs, OWNER, SID, FILE, BYTES
from ai_run_policy import run_context
from ai_standing_approval import approve_file, check_application
from ai_run_approval_override import read, save, process_pending


def test_switch_on_approves_existing_exact_run_proposal_then_off_preserves_approved_writer(isolated_store, monkeypatch):
    store=isolated_store
    job=seed(store, monkeypatch, enabled=False)
    with run_context(store, job['payload'], job) as ctx:
        item=store.enqueue_proposals(SID, FILE, '2.4.6', [proposal(store)])
        before=read(store,OWNER,SID,ctx.run_id)
        assert before['enabled'] is False
        updated=save(store,OWNER,SID,ctx.run_id,True,0,before['source_revision'])
        assert updated['revision']==1 and updated['enabled'] is True
        process_pending(store,dict(owner=OWNER,scan_id=SID,run_id=ctx.run_id,source_revision=before['source_revision']))
        assert store.get_hitl_item(item)['status']=='approved'
        save(store,OWNER,SID,ctx.run_id,False,1,before['source_revision'])
        writes=[job for job in apply_jobs(store) if not json.loads(job['payload']).get('phase')]
        check_application(store,json.loads(writes[0]['payload']),working=BYTES)
        second=store.enqueue_proposals(SID,FILE,'1.1.1',[proposal(store,rule='1.1.1',locator='ppt/slides/slide1.xml#rId1')])
        approve_file(store,ctx)
        assert store.get_hitl_item(second)['status']=='pending'
        with pytest.raises(ValueError,match='changed'):
            save(store,OWNER,SID,ctx.run_id,True,1,before['source_revision'])


def test_override_cannot_cross_owner_or_change_snapshot(isolated_store,monkeypatch):
    store=isolated_store;job=seed(store,monkeypatch)
    with run_context(store,job['payload'],job) as ctx:
        initial=read(store,OWNER,SID,ctx.run_id)
        with pytest.raises(ValueError):read(store,'other@example.test',SID,ctx.run_id)
        with pytest.raises(ValueError,match='source revision'):
            save(store,OWNER,SID,ctx.run_id,True,0,'wrong-source')
        with pytest.raises(ValueError):save(store,OWNER,SID,ctx.run_id,1,0,initial['source_revision'])


def test_local_source_requires_exact_cached_source_and_corrected_bytes(isolated_store,monkeypatch):
    from hashlib import sha256
    import scanner,blob
    store=isolated_store;job=seed(store,monkeypatch,enabled=False)
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE scan_runs SET source='local' WHERE id=%s",(SID,))
        store._db.execute(cur,"INSERT INTO scan_inventory(scan_id,file,checksum) VALUES(%s,%s,%s)",(SID,FILE,sha256(b'original').hexdigest()))
    monkeypatch.setattr(scanner,'read_cached_source',lambda *a,**k:b'original')
    monkeypatch.setattr(blob,'download_remediated',lambda *a:BYTES)
    from ai_standing_approval import _source
    assert _source(store,OWNER,SID,FILE)['corrected_sha256']==sha256(BYTES).hexdigest()
    monkeypatch.setattr(scanner,'read_cached_source',lambda *a,**k:b'corrupt-original')
    with pytest.raises(ValueError,match='Exact assessed'):_source(store,OWNER,SID,FILE)
    monkeypatch.setattr(scanner,'read_cached_source',lambda *a,**k:b'original')
    monkeypatch.setattr(blob,'download_remediated',lambda *a:b'wrong')
    with pytest.raises(ValueError,match='Exact assessed'):_source(store,OWNER,SID,FILE)


def test_unsupported_ai_run_switch_is_readonly(isolated_store,monkeypatch):
    store=isolated_store;job=seed(store,monkeypatch,enabled=False)
    with run_context(store,job['payload'],job) as ctx:
        with store._db.cursor() as cur:
            store._db.execute(cur,"UPDATE ai_spending_run_policies SET policy_json=%s WHERE run_id=%s",(json.dumps({'ai':0}),ctx.run_id))
        state=read(store,OWNER,SID,ctx.run_id)
        assert state['supported'] is False and state['enabled'] is False
        with pytest.raises(ValueError,match='did not authorize'):
            save(store,OWNER,SID,ctx.run_id,True,0,state['source_revision'])


def test_approval_coordination_uses_existing_remediate_worker_lane(isolated_store,monkeypatch):
    import core,handlers
    from worker import HANDLERS,FatalJobError
    store=isolated_store;job=seed(store,monkeypatch,enabled=False)
    with run_context(store,job['payload'],job) as ctx:
        state=read(store,OWNER,SID,ctx.run_id)
        save(store,OWNER,SID,ctx.run_id,True,0,state['source_revision'])
        pending=store.enqueue_proposals(SID,FILE,'2.4.6',[proposal(store)])
        coordination=[row for row in apply_jobs(store) if json.loads(row['payload']).get('phase')][0]
        assert coordination['type']=='apply_approved_values'
        assert 'approve_run_ai' not in HANDLERS
        monkeypatch.setenv('ACP_WORKER_ROLE','remediate')
        types=core._worker_job_types(0,2)
        assert coordination['type'] in types
        # Clear the admission job so this claim specifically proves coordination placement.
        with store._db.cursor() as cur:
            store._db.execute(cur,"UPDATE jobs SET status='done' WHERE id=%s",(job['id'],))
        claimed=store.claim_job('approval-worker',job_types=types)
        assert claimed['id']==coordination['id']
        handlers._apply_approved_values(claimed['payload'],claimed)
        assert store.get_hitl_item(pending)['status']=='approved'
        bad={**claimed['payload'],'file':'unapproved.docx'}
        with pytest.raises(FatalJobError,match='Invalid current-run'):
            handlers._apply_approved_values(bad,claimed)


def test_uploaded_null_record_checksum_uses_immutable_contribution_proof(isolated_store,monkeypatch):
    from hashlib import sha256
    import scanner,blob
    store=isolated_store;job=seed(store,monkeypatch,enabled=True)
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE scan_runs SET source='local' WHERE id=%s",(SID,))
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE stage_executions SET input_snapshot_id=%s WHERE execution_id=%s",(store.remediation_source_revision(SID),job['batch_id']))
    monkeypatch.setattr(scanner,'read_cached_source',lambda *a,**k:b'original')
    monkeypatch.setattr(blob,'download_remediated',lambda *a:BYTES)
    with run_context(store,job['payload'],job) as ctx:
        item=store.enqueue_proposals(SID,FILE,'2.4.6',[proposal(store)])
        snapshot=store.get_hitl_item(item)['proposal_snapshot_ids'][0]
        revision=store.remediation_source_revision(SID)
        with store._db.cursor() as cur:
            store._db.execute(cur,"INSERT INTO remediation_contribution_proposals(owner_id,scan_id,run_id,proposal_id,proposal_sha256,source_sha256,assessment_revision,file,rule_id,item_id,finding_ids_json,created_at) VALUES(%s,%s,%s,%s,'immutable-proposal',%s,%s,%s,'2.4.6',%s,'[]','2026-09-12')",
                (OWNER,SID,ctx.run_id,snapshot,sha256(b'original').hexdigest(),revision,FILE,item))
        assert store.get_file_record(SID,FILE).get('checksum') is None
        assert store.get_source_checksum(SID,FILE) is None
        approve_file(store,ctx)
        assert store.get_hitl_item(item)['status']=='approved'
        payload=json.loads([row for row in apply_jobs(store) if not json.loads(row['payload']).get('phase')][0]['payload'])
        check_application(store,payload,working=BYTES)
        monkeypatch.setattr(scanner,'read_cached_source',lambda *a,**k:b'corrupt')
        with pytest.raises(ValueError,match='Exact assessed'):
            check_application(store,payload,working=BYTES)
