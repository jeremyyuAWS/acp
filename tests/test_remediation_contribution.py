"""Exact contribution evidence fixtures; never calibration or production outcomes."""
import json
import sys
from pathlib import Path
from hashlib import sha256
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
import remediation_contribution as c


def baseline(n=5):
    return dict(owner_id='owner',scan_id='scan',run_id='run',snapshot_id='assessment',
                baseline_json=c.encoded([dict(finding_id=str(i),file='a.docx',rule_id='1.1.1',instance_key=str(i)) for i in range(n)]), files_json='["a.docx"]')


def proposal(id='p', ids=('0','1','2','3','4'), origin='fallback_ai', **extra):
    return dict(owner_id='owner',scan_id='scan',run_id='run',proposal_id=id,
                proposal_sha256='d'*64,source_sha256='a'*64,assessment_revision='assessment',finding_ids_json=c.encoded(list(ids)),origin=origin,**extra)


def event(p, **extra):
    return {**p, 'id':'event','proposal_snapshot_id':p['proposal_id'],
        'outcome':'verified_cleared','regressions':'[]','approval_action':'approve',
        'approval_event_id':'approval','artifact_sha256':'b'*64,'source_revision':'assessment',
        'approval_source_revision':'assessment','actual_source_sha256':'a'*64,
        'actual_approved_value_sha256':'v'*64,'approved_value_sha256':'v'*64,
        'approval_value_sha256':'v'*64,'proposal_snapshot_ids':c.encoded([p['proposal_id']]),**extra}


def test_one_proposal_covers_five_findings_and_retries_revisions_stay_five():
    p=proposal(); revision=proposal('revision')
    data=c.aggregate(baseline(),[p,p,revision,revision],[])
    assert data['baseline_total']==5
    assert data['contributions']['fallback_ai']==5
    assert data['outcomes']['awaiting_review']==5
    assert sum(data['outcomes'].values())==5


def test_first_usable_generation_is_not_fallback_additional():
    data=c.aggregate(baseline(),[proposal(origin='first_ai'),proposal('next')],[])
    assert data['contributions']==dict(rules=0,first_ai=5,fallback_ai=0)


@pytest.mark.parametrize('change',[
    {'proposal_snapshot_id':'wrong'}, {'actual_source_sha256':'stale'},
    {'actual_approved_value_sha256':'edited'}, {'approval_value_sha256':'other'},
    {'approval_event_id':None}, {'artifact_sha256':None}, {'regressions':None},
    {'outcome':'verified_still_failing'}, {'approval_source_revision':'stale'},
])
def test_inexact_or_failed_verification_never_fixed(change):
    p=proposal()
    data=c.aggregate(baseline(),[p],[event(p,**change)])
    assert data['outcomes']['fixed']==0
    assert data['outcomes']['unresolved']==5


def test_later_failure_supersedes_old_success_and_retry_replay_cannot_inflate():
    p=proposal()
    assert c.aggregate(baseline(),[p],[event(p)])['outcomes']['fixed']==5
    result=c.aggregate(baseline(),[p],[event(p),event(p,outcome='could_not_verify')])
    assert result['outcomes']['fixed']==0
    assert result['outcomes']['unresolved']==5


def test_owner_isolation_even_with_colliding_finding_and_proposal_ids():
    p=proposal(); other={**p,'owner_id':'other'}
    result=c.aggregate(baseline(),[other], [event(other)])
    assert result['outcomes']['unavailable']==5
    assert result['coverage']=='partial'
    result=c.aggregate(baseline(),[p],[event(p,owner_id='other')])
    assert result['outcomes']['fixed']==0


def test_partial_processing_unresolved_and_approval_partition():
    p=proposal(ids=['0'],origin='rules')
    a=dict(human_approval_id='audit',approval_snapshot_ids='["p"]',status='approved',approved_proposal_snapshot_ids='["p"]',approved_value_sha256='v',approved_source_revision='assessment')
    data=c.aggregate(baseline(),[p],[],dispositions={'1':'remediation_failed'},approvals={'p':a})
    assert data['outcomes']==dict(fixed=0,awaiting_review=0,approved=1,unresolved=1,processing=0,unavailable=3)
    assert c.aggregate(baseline(),[],[],active_files=['a.docx'])['outcomes']['processing']==5
    assert data['reviewer']['checked_proposals'] is None


@pytest.fixture
def store(monkeypatch,tmp_path):
    import store as st
    monkeypatch.setattr(st,'_SQLITE_PATH',tmp_path/'contribution.db')
    return st.Store()


def admitted(store, count=5):
    store.init_scan_run('scan','local',1,'2026-09-08T00:00:00Z','rubric','hash',owner='owner')
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) VALUES(%s,%s,%s,'FAIL',%s)",('scan','a.docx','1.1.1',count))
    result=store.enqueue_stage_batch('scan','remediate','remediate_file',[{'file':'a.docx','owner':'owner','scan_id':'scan'}],snapshot_id='assessment',request_fingerprint='fixture')
    return result['batch_id']


def test_admission_freezes_selected_baseline_before_jobs_visible_and_replay_does_not_grow(store):
    run=admitted(store)
    first=c.read_contribution(store,'owner','scan',run)
    assert first['baseline_total']==5
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE scan_rule_traces SET finding_count=99 WHERE scan_id='scan'")
    assert c.read_contribution(store,'owner','scan',run)['baseline_total']==5
    with pytest.raises(PermissionError): c.read_contribution(store,'other','scan',run)


def test_capture_requires_explicit_multi_finding_membership_and_exact_source(store):
    run=admitted(store)
    ctx=SimpleNamespace(owner_id='owner',run_id=run,scan_id='scan',file='a.docx')
    p=dict(locator='image',proposed_value='A tree',source='rules')
    token=c.SOURCE.set(('scan','a.docx','a'*64))
    try:
        with store._db.cursor() as cur:
            c.capture(store._db,cur,ctx,snapshot_id='p',proposal=p,scan_id='scan',file='a.docx',rule_id='1.1.1',item_id='item',attempt_id=None)
        assert c.read_contribution(store,'owner','scan',run)['contributions']['rules']==0
        ids=[f['finding_id'] for f in c.read_contribution(store,'owner','scan',run)['findings']]
        with store._db.cursor() as cur:
            c.capture(store._db,cur,ctx,snapshot_id='p',proposal={**p,'baseline_finding_ids':ids},scan_id='scan',file='a.docx',rule_id='1.1.1',item_id='item',attempt_id=None)
        assert c.read_contribution(store,'owner','scan',run)['contributions']['rules']==5
    finally: c.SOURCE.reset(token)


def seed_exact_writer(store):
    run=admitted(store, count=1)
    ctx=SimpleNamespace(owner_id='owner',run_id=run,scan_id='scan',file='a.docx')
    p=dict(locator='image',before='',proposed_value='A tree',source='rules')
    token=c.SOURCE.set(('scan','a.docx','a'*64))
    try:
        item=store.enqueue_proposals('scan','a.docx','1.1.1',[p])
        with store._db.cursor() as cur:
            c.capture(store._db,cur,ctx,snapshot_id='exact',proposal=p,scan_id='scan',file='a.docx',rule_id='1.1.1',item_id=item,attempt_id=None)
        store.update_hitl_item(item,'approved',None,None)
        store.approve_proposal_values(item,[])
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE hitl_queue SET approved_proposal_snapshot_ids=%s,approved_source_revision=%s,approved_value_sha256=%s WHERE id=%s", ('["exact"]','assessment',c.digest(['A tree']),item))
        store.record_hitl_event('scan','a.docx','1.1.1',item,'approve',proposal_snapshot_ids=['exact'],source_revision='assessment',approved_value_sha256=c.digest(['A tree']))
    finally: c.SOURCE.reset(token)
    return run,item


def test_writer_proof_binds_approved_values_actual_source_and_durable_artifact(store):
    run,item=seed_exact_writer(store)
    tickets=c.writer_tickets(store,'scan','a.docx',[item],'a'*64,actual_values={'image':'A tree'})
    assert len(tickets)==1
    c.record_writer_result(store,tickets,outcome='verified_cleared',artifact_sha256='b'*64,reference='stored fixture artifact',writer_attempt_id='write1')
    result=c.read_contribution(store,'owner','scan',run)
    assert result['outcomes']['fixed']==1
    assert result['findings'][0]['approval_kind']=='human'
    c.record_writer_result(store,tickets,outcome='could_not_verify',artifact_sha256=None,reference='failed retry',writer_attempt_id='write2')
    assert c.read_contribution(store,'owner','scan',run)['outcomes']['fixed']==0


def test_writer_replay_idempotent_stale_source_and_queue_revision_fail_closed(store):
    run,item=seed_exact_writer(store)
    tickets=c.writer_tickets(store,'scan','a.docx',[item],'c'*64,actual_values={'image':'A tree'})
    for _ in range(2):
        c.record_writer_result(store,tickets,outcome='verified_cleared',artifact_sha256='b'*64,reference='replay',writer_attempt_id='write1')
    assert len(store.list_ai_validation_outcomes('scan'))==1
    assert c.read_contribution(store,'owner','scan',run)['outcomes']['fixed']==0
    store.approve_proposal_values(item,['An edited tree'])
    assert c.writer_tickets(store,'scan','a.docx',[item],'a'*64,actual_values={'image':'A tree'})==[]


def test_erase_removes_contribution_scope(store):
    run,item=seed_exact_writer(store)
    store.delete_scan('scan','owner')
    with store._db.cursor() as cur:
        for table in ('remediation_contribution_runs','remediation_contribution_proposals'):
            store._db.execute(cur,f'SELECT COUNT(*) AS n FROM {table}')
            assert store._db.fetchone(cur)['n']==0


def test_writer_input_must_match_exact_approved_values_even_if_queue_is_newer(store):
    run,item=seed_exact_writer(store)
    assert c.writer_tickets(store,'scan','a.docx',[item],'a'*64,actual_values={'image':'A previous value'}) == []
    assert c.writer_tickets(store,'scan','a.docx',[item],'a'*64,actual_values={}) == []


def test_later_actual_retry_can_recover_after_failed_verification(store):
    run,item=seed_exact_writer(store)
    tickets=c.writer_tickets(store,'scan','a.docx',[item],'a'*64,actual_values={'image':'A tree'})
    for attempt,outcome in [('one','verified_cleared'),('two','could_not_verify'),('three','verified_cleared')]:
        c.record_writer_result(store,tickets,outcome=outcome,artifact_sha256='b'*64,reference='same payload',writer_attempt_id=attempt)
    assert c.read_contribution(store,'owner','scan',run)['outcomes']['fixed']==1
    assert len(store.list_ai_validation_outcomes('scan'))==3


def test_later_lane_regression_cannot_credit_earlier_lane_against_final_artifact(store,monkeypatch):
    import core, handlers
    from proposals import Verification
    run,item=seed_exact_writer(store)
    monkeypatch.setattr(core,'store',store)
    monkeypatch.setattr(handlers,'_verify_residual',lambda data,file: Verification(True,set()))
    # Source fingerprint is for the bytes that this actual write will consume.
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE remediation_contribution_proposals SET source_sha256=%s",(sha256(b'before').hexdigest(),))
    pending=[]
    residual={'verification':Verification(True,{'1.1.1'})}
    handlers._apply_one_value_kind(scan_id='scan',filename='a.docx',working=b'before',
        values={'image':'A tree'},scs_to_clear={'1.1.1'},
        write_fn=lambda working,values:(b'after',[{'locator':'image','before':'','after':'A tree'}],[]),
        diff_rule_id='1.1.1',credit_rule_ids=('1.1.1',),noun='alt text',job={},pending_credits=pending,
        residual_state=residual)
    assert len(pending)==1
    # Another lane mutates the final artifact and reintroduces the first failure.
    residual['verification']=Verification(True,{'1.1.1'})
    pending[0]()
    rows=store.list_ai_validation_outcomes('scan')
    assert rows[-1]['outcome']=='verified_still_failing'
    assert c.read_contribution(store,'owner','scan',run)['outcomes']['fixed']==0
