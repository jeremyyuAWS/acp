"""Synthetic local DB: advance authorization is real, scoped, and idempotent."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest
import core
import handlers
from ai_run_policy import run_context, read_run_budget, normalize_run_policy
from ai_standing_approval import approve_file, check_application, authorization
from remediation_impact_settings import normalize_policy, snapshot_impact_policy

OWNER, SID, FILE = 'owner@example.test', 'standing', 'deck.pptx'
BYTES = b'synthetic verified working artifact'
DIGEST = sha256(BYTES).hexdigest()


def seed(store, monkeypatch, enabled=True, review=False):
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {'sp': 'synthetic-token'})
    import release_artifacts
    monkeypatch.setattr(release_artifacts, 'require_current_source', lambda *a, **k: None)
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,'done','sharepoint')", (SID, OWNER))
        store._db.execute(cur, "INSERT INTO file_records(scan_id,file,drive_file_id,source_modified,corrected_sha256,remediated_at) VALUES(%s,%s,'source-id','2026-09-01',%s,'2026-09-02')", (SID, FILE, DIGEST))
    policy = {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '1.00', 'auto_approve_ai': enabled}
    if review: policy['ai_review'] = {'enabled':True}
    batch = store.enqueue_stage_batch(SID, 'remediate', 'remediate_file', [{
        'scan_id': SID, 'file': FILE, 'owner': OWNER, 'source': 'sharepoint',
        'remediation_impact_policy': policy}], snapshot_id=store.remediation_source_revision(SID), request_fingerprint='standing')
    return store.get_job(batch['job_ids'][0])


def register_review(store, ctx, p, verdict='accept'):
    """Record the independent second-model review this path now requires.

    Mirrors what the review chain writes in production: an attempt whose retained
    output IS the drafted value, a trace link binding it to the paid call, and a
    receipt over the exact draft digest.
    """
    from ai_attempt_history import AttemptHistory
    from ai_review_chain import _save_review
    operation, attempt = f'op-{p["model_call_id"]}', f'attempt-{p["model_call_id"]}'
    AttemptHistory(store._db).begin(OWNER, SID, ctx.run_id, operation, attempt, file=FILE,
        input_sha256=DIGEST, model=p['model'], provider='synthetic', purpose='draft')
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE ai_attempt_history SET result_json=%s WHERE attempt_id=%s',
            (json.dumps({'text': p['proposed_value']}), attempt))
        store._db.execute(cur, 'INSERT INTO ai_attempt_trace_links VALUES(%s,%s,%s,%s)',
            (OWNER, ctx.run_id, attempt, p['model_call_id']))
    _save_review(ctx, operation, sha256(p['proposed_value'].encode()).hexdigest(), {'verdict': verdict})
    return p


def proposal(store, rule='2.4.6', locator='slide:1', value='Clear title', model='fallback-2', review='accept'):
    call_id = store.record_ai_call(surface='synthetic', provider='synthetic', model=model,
        zone='local', latency_ms=0, ok=True, scan_id=SID, file=FILE)
    p = {'locator': locator, 'before': '', 'proposed_value': value, 'source': 'AI synthetic fixture',
         'model': model, 'model_call_id': call_id}
    # Standing approval is the one path with no human reading the draft, so the
    # second-model review is mandatory there. Fixtures that expect auto-approval must
    # carry one; pass review=None to exercise the fail-closed path.
    if review is not None:
        from ai_run_policy import optional_current_run_context
        ctx = optional_current_run_context()
        if ctx is not None:
            register_review(store, ctx, p, review)
    return p


def rows(store, table):
    with store._db.cursor() as cur:
        store._db.execute(cur, f'SELECT * FROM {table}')
        return store._db.fetchall(cur)


def apply_jobs(store):
    return [j for j in rows(store, 'jobs') if j['type'] == 'apply_approved_values']


def test_later_fallbacks_approve_once_without_human_confirmation(isolated_store, monkeypatch):
    s=isolated_store; job=seed(s, monkeypatch)
    with run_context(s, job['payload'], job) as ctx:
        first=s.enqueue_proposals(SID, FILE, '2.4.6', [proposal(s)])
        approve_file(s, ctx)
        approve_file(s, ctx)
        # A later arrival in this same accepted run does not need another opt-in.
        second=s.enqueue_proposals(SID, FILE, '1.1.1', [proposal(s, locator='ppt/slides/slide1.xml#rId1', model='fallback-1')])
        approve_file(s, ctx)
        approve_file(s, ctx)
    assert [s.get_hitl_item(i)['status'] for i in (first,second)] == ['approved','approved']
    assert len(apply_jobs(s)) == 2
    assert all(not s.get_hitl_item(i)['applied'] for i in (first,second))
    assert len([e for e in rows(s,'hitl_events') if e['action']=='standing_approve']) == 2
    logs=[r for r in rows(s,'decision_log') if r['action']=='hitl.approved_under_run_policy']
    assert len(logs)==2 and all(r['actor']=='system' for r in logs)
    assert all(json.loads(r['detail'])['authorized_by']==OWNER for r in logs)
    assert not [r for r in rows(s,'decision_log') if r['action']=='hitl.approved']
    assert read_run_budget(s,OWNER,SID,ctx.run_id)['policy']['auto_approve_ai'] is True
    assert not [j for j in rows(s,'jobs') if j['type'] in {'publish_file','release_continue'}]


def test_multiple_rows_commit_one_apply_job_and_recheck_exact_bytes(isolated_store, monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        for rule in ('2.4.6','1.1.1'):
            s.enqueue_proposals(SID,FILE,rule,[proposal(s)])
        approve_file(s,ctx)
    jobs=apply_jobs(s);assert len(jobs)==1
    payload=json.loads(jobs[0]['payload'])
    check_application(s,payload,working=BYTES)
    with pytest.raises(ValueError,match='bytes'):
        check_application(s,payload,working=b'different')
    item=payload['standing_approval']['items'][0]
    s.update_hitl_item(item['id'],'rejected')
    with pytest.raises(ValueError,match='changed'):
        check_application(s,payload,working=BYTES)


@pytest.mark.parametrize('mutation', ['partial','empty','no_model','explain','unsupported','snapshot','stale_source','no_source','no_artifact'])
def test_ineligible_evidence_never_auto_approves(isolated_store,monkeypatch,mutation):
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        p=proposal(s)
        if mutation=='empty': p['proposed_value']=''
        if mutation=='no_model': p.pop('model_call_id')
        if mutation=='explain': p['explain_only']=True
        item=s.enqueue_proposals(SID,FILE,'1.3.2' if mutation=='unsupported' else '2.4.6',[p],finding_count=2 if mutation=='partial' else 1)
        with s._db.cursor() as cur:
            if mutation=='snapshot':s._db.execute(cur,"UPDATE hitl_queue SET proposal_snapshot_ids='[]' WHERE id=%s",(item,))
            if mutation=='stale_source':s._db.execute(cur,"UPDATE scan_runs SET scope='changed' WHERE id=%s",(SID,))
            if mutation=='no_source':s._db.execute(cur,"UPDATE file_records SET source_modified=NULL WHERE scan_id=%s",(SID,))
            if mutation=='no_artifact':s._db.execute(cur,"UPDATE file_records SET corrected_sha256=NULL WHERE scan_id=%s",(SID,))
        try:approve_file(s,ctx)
        except ValueError:pass
    assert s.get_hitl_item(item)['status']=='pending'
    assert apply_jobs(s)==[]


def test_default_off_never_uses_later_owner_preferences(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch,False)
    with run_context(s,job['payload'],job) as ctx:
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)])
        s.set_setting('unused-new-preference','true')
        approve_file(s,ctx)
    assert s.get_hitl_item(item)['status']=='pending'
    assert not apply_jobs(s)
    assert 'auto_approve_ai' not in normalize_run_policy({'ai':1,'ai_budget_usd':'1.00'})


def test_caller_cannot_add_optin_to_accepted_run(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch,False)
    payload=deepcopy(job['payload']);payload['remediation_impact_policy']['auto_approve_ai']=True
    from ai_spending_budget import BudgetError
    with pytest.raises(BudgetError):
        with run_context(s,payload,job):pass


@pytest.mark.parametrize('value',[1,'true',None,{},[]])
def test_boolean_must_be_explicit(value):
    with pytest.raises(ValueError):normalize_policy({'rule_based':2,'ai':1,'ai_budget_usd':'1.00','auto_approve_ai':value})


def test_worker_calls_authorization_after_work_with_original_context(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    def work(payload,job):s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)])
    monkeypatch.setattr(handlers,'_remediate_file_with_policy',work)
    handlers._remediate_file(job['payload'],job)
    assert len(apply_jobs(s))==1


@pytest.mark.parametrize('mutation', ['cancelled','obsolete','permission','provider','old_call','wrong_model','failed_call'])
def test_live_authority_and_current_generation_are_required(isolated_store, monkeypatch, mutation):
    import ai_standing_approval as standing
    import release_artifacts
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        p=proposal(s)
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[p])
        with s._db.cursor() as cur:
            if mutation=='cancelled':s._db.execute(cur,"UPDATE stage_executions SET cancel_requested_at='now' WHERE execution_id=%s",(ctx.run_id,))
            if mutation=='obsolete':s._db.execute(cur,"UPDATE stage_executions SET is_current=0 WHERE execution_id=%s",(ctx.run_id,))
            if mutation=='old_call':s._db.execute(cur,"UPDATE ai_calls SET ts='2020-01-01T00:00:00+00:00' WHERE id=%s",(p['model_call_id'],))
            if mutation=='wrong_model':s._db.execute(cur,"UPDATE ai_calls SET model='different' WHERE id=%s",(p['model_call_id'],))
            if mutation=='failed_call':s._db.execute(cur,"UPDATE ai_calls SET ok=0 WHERE id=%s",(p['model_call_id'],))
        def refuse(*a,**k):raise ValueError('Unavailable')
        if mutation=='permission':monkeypatch.setattr(standing,'require_access',refuse)
        if mutation=='provider':monkeypatch.setattr(release_artifacts,'require_current_source',refuse)
        try:approve_file(s,ctx)
        except ValueError:pass
    assert s.get_hitl_item(item)['status']=='pending'
    assert not apply_jobs(s)


@pytest.mark.parametrize('outcome',['verified','cannot_verify','storage_failed','cancel_before_storage'])
def test_real_office_writer_only_credits_saved_verified_output(isolated_store,monkeypatch,outcome):
    import sys
    from test_apply_approved_values import _deck, _slide_xml, _Blob
    from proposals import Verification
    s=isolated_store;job=seed(s,monkeypatch)
    original=_deck('Picture 1'); artifact=sha256(original).hexdigest()
    with s._db.cursor() as cur:
        s._db.execute(cur,'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s',(artifact,SID))
    with run_context(s,job['payload'],job) as ctx:
        item=s.enqueue_proposals(SID,FILE,'1.1.1',[proposal(s,locator='ppt/slides/slide1.xml#Picture 1',value='Quarterly sales chart')])
        approve_file(s,ctx)
    assert not s.get_hitl_item(item)['applied']
    blob=_Blob(original)
    monkeypatch.setitem(sys.modules,'blob',blob)
    seen=[]
    def verify(data,file):
        seen.append(data)
        if outcome=='cannot_verify':return Verification(False,())
        if outcome=='cancel_before_storage' and data!=original:
            with s._db.cursor() as cur:s._db.execute(cur,"UPDATE stage_executions SET cancel_requested_at='now' WHERE execution_id=%s",(ctx.run_id,))
        return Verification(True, {'1.1.1'} if 'descr="Quarterly sales chart"' not in _slide_xml(data) else set())
    monkeypatch.setattr(handlers,'_verify_residual',verify)
    if outcome=='storage_failed':monkeypatch.setattr(blob,'upload_remediated',lambda *a:None)
    payload=json.loads(apply_jobs(s)[0]['payload'])
    if outcome in {'storage_failed','cancel_before_storage'}:
        with pytest.raises((ValueError,RuntimeError)):handlers._apply_approved_values(payload,{})
    else:handlers._apply_approved_values(payload,{})
    assert len(seen)>=2 and seen[0]==original and seen[-1]!=original
    assert bool(s.get_hitl_item(item)['applied']) is (outcome=='verified')
    if outcome=='verified':
        assert 'descr="Quarterly sales chart"' in _slide_xml(blob.data)
        assert s.get_file_record(SID,FILE)['corrected_sha256']==sha256(blob.data).hexdigest()
        handlers._apply_approved_values(payload,{})
        assert len(blob.uploads)==1
    else:assert not blob.uploads
    assert not [j for j in rows(s,'jobs') if j['type'] in {'publish_file','release_continue','deliver_corrected_copy'}]


def test_manual_job_cannot_sweep_obsolete_system_approval(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)])
        approve_file(s,ctx)
    with s._db.cursor() as cur:s._db.execute(cur,'UPDATE stage_executions SET is_current=0 WHERE execution_id=%s',(ctx.run_id,))
    with pytest.raises(ValueError,match='authorization'):
        handlers._apply_approved_values({'scan_id':SID,'file':FILE},{})
    assert not s.get_hitl_item(item)['applied']


def test_system_approval_history_is_not_a_human_review(isolated_store,monkeypatch):
    from remediation_run_insights import read_insights
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)])
        approve_file(s,ctx)
    result=read_insights(s,OWNER,SID,ctx.run_id)
    assert result['standing_approval']=={'enabled':True,'authorized_by':OWNER}
    assert len(result['proposals'][0]['system_approvals'])==1
    assert not result['proposals'][0].get('human_reviews')
    assert not result['proposals'][0]['version_verified']


def test_incomplete_exception_does_not_hold_back_eligible_file_row(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        exception=s.enqueue_proposals(SID,FILE,'1.1.1',[proposal(s)],finding_count=3)
        valid=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)])
        approve_file(s,ctx)
    assert s.get_hitl_item(exception)['status']=='pending'
    assert s.get_hitl_item(valid)['status']=='approved'
    assert len(apply_jobs(s))==1


def test_future_defaults_roundtrip_but_do_not_reauthorize_existing_run(isolated_store,monkeypatch):
    from remediation_impact_settings import read_impact_policy, save_impact_policy
    s=isolated_store;job=seed(s,monkeypatch,False)
    selected={'rule_based':2,'ai':1,'ai_budget_usd':'1.00','auto_approve_ai':True,
              'ai_review':{'enabled':True}}
    saved=save_impact_policy(s,OWNER,OWNER,selected,0)
    assert saved['policy']['auto_approve_ai'] is True
    assert read_impact_policy(s,OWNER)['auto_approve_ai'] is True
    assert 'auto_approve_ai' not in read_impact_policy(s,'other@example.test')
    new=snapshot_impact_policy(s,OWNER)
    old=snapshot_impact_policy(s,OWNER,{**selected,'auto_approve_ai':False})
    assert new['snapshot_id']!=old['snapshot_id']
    with run_context(s,job['payload'],job) as ctx:
        assert ctx.policy['auto_approve_ai'] is False
        assert read_run_budget(s,OWNER,SID,ctx.run_id)['policy']['auto_approve_ai'] is False
        with pytest.raises(ValueError):authorization(s,OWNER,SID,ctx.run_id)


@pytest.mark.parametrize('zone,budget', [('any','1.00'),('local','0.00'),('any','0.00')])
def test_explicit_approval_does_not_require_model_reviewer(zone,budget):
    base={'rule_based':2,'ai':1,'ai_budget_usd':budget,'auto_approve_ai':True,'ai_zone':zone}
    for review in (None,{'enabled':False}):
        policy=dict(base) if review is None else {**base,'ai_review':review}
        assert normalize_policy(policy)['auto_approve_ai'] is True
        assert normalize_run_policy(policy)['auto_approve_ai'] is True


def test_explicit_run_consent_applies_exact_suggestion_without_model_review(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s,review=None)])
        approve_file(s,ctx)
    assert s.get_hitl_item(item)['status']=='approved'
    assert apply_jobs(s)
    assert not s.get_hitl_item(item).get('applied')  # approval is not a verified fix


@pytest.mark.parametrize('policy',[{'ai':1},{'ai':0,'ai_budget_usd':'1.00'}])
def test_optin_without_ai_and_explicit_budget_never_snapshots(policy):
    with pytest.raises(ValueError):normalize_policy({'rule_based':2,**policy,'auto_approve_ai':True})
    from ai_spending_budget import BudgetError
    with pytest.raises(BudgetError):normalize_run_policy({**policy,'auto_approve_ai':True})


def test_failed_job_enqueue_rolls_back_decision_and_audit_together(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    def fail(*a,**k):raise RuntimeError('Synthetic queue failure')
    with run_context(s,job['payload'],job) as ctx:
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)])
        monkeypatch.setattr(s,'enqueue_job',fail)
        with pytest.raises(RuntimeError):approve_file(s,ctx)
    assert s.get_hitl_item(item)['status']=='pending'
    assert not [e for e in rows(s,'hitl_events') if e['action']=='standing_approve']
    assert not [e for e in rows(s,'decision_log') if e['action']=='hitl.approved_under_run_policy']


def test_system_authorization_contribution_still_requires_exact_writer_evidence():
    from test_remediation_contribution import baseline, proposal, event
    from remediation_contribution import aggregate
    p=proposal()
    approval=dict(authorization_event_id='system-event',authorization_action='standing_approve',
        approval_snapshot_ids='["p"]',status='approved',approved_proposal_snapshot_ids='["p"]',
        approved_value_sha256='v',approved_source_revision='assessment')
    approved=aggregate(baseline(),[p],[],approvals={'p':approval})
    assert approved['outcomes']['fixed']==0
    assert approved['outcomes']['approved']==5
    assert all(f['approval_kind']=='run_authorization' for f in approved['findings'])
    verified=aggregate(baseline(),[p],[event(p,approval_action='standing_approve')])
    assert verified['outcomes']['fixed']==5
    assert all(f['approval_kind']=='run_authorization' for f in verified['findings'])
    stale=aggregate(baseline(),[p],[event(p,approval_action='standing_approve',actual_source_sha256='stale')])
    assert stale['outcomes']['fixed']==0


@pytest.mark.parametrize('verdict',['accept','revise','unable','missing','wrong_digest'])
def test_optional_review_must_resolve_for_exact_draft(isolated_store,monkeypatch,verdict):
    from ai_attempt_history import AttemptHistory
    from ai_review_chain import _save_review
    s=isolated_store;job=seed(s,monkeypatch,review=True)
    with run_context(s,job['payload'],job) as ctx:
        p=proposal(s,review=None)
        h=AttemptHistory(s._db)
        h.begin(OWNER,SID,ctx.run_id,'operation','attempt',file=FILE,input_sha256=DIGEST,
            model=p['model'],provider='synthetic',purpose='draft')
        with s._db.cursor() as cur:
            s._db.execute(cur,'UPDATE ai_attempt_history SET result_json=%s WHERE attempt_id=%s',
                (json.dumps({'text':p['proposed_value']}),'attempt'))
            s._db.execute(cur,'INSERT INTO ai_attempt_trace_links VALUES(%s,%s,%s,%s)',
                (OWNER,ctx.run_id,'attempt',p['model_call_id']))
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[p])
        if verdict!='missing':
            digest=sha256(p['proposed_value'].encode()).hexdigest() if verdict!='wrong_digest' else DIGEST
            _save_review(ctx,'operation',digest,{'verdict':'accept' if verdict=='wrong_digest' else verdict})
        approve_file(s,ctx)
    assert (s.get_hitl_item(item)['status']=='approved') is (verdict=='accept')
    assert bool(apply_jobs(s)) is (verdict=='accept')


def test_partial_first_attempt_then_complete_fallback_needs_no_new_authorization(isolated_store,monkeypatch):
    s=isolated_store;job=seed(s,monkeypatch)
    with run_context(s,job['payload'],job) as ctx:
        item=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s)],finding_count=2)
        approve_file(s,ctx)
        assert s.get_hitl_item(item)['status']=='pending'
        same=s.enqueue_proposals(SID,FILE,'2.4.6',[proposal(s,locator='slide:1'),proposal(s,locator='slide:2')],finding_count=2)
        assert same==item
        approve_file(s,ctx)
    assert s.get_hitl_item(item)['status']=='approved'
    assert len(apply_jobs(s))==1


def test_saved_writer_receipt_attaches_to_system_authorization(isolated_store):
    from test_remediation_contribution import seed_exact_writer
    import remediation_contribution as contribution
    s=isolated_store
    run,item=seed_exact_writer(s)
    with s._db.cursor() as cur:
        s._db.execute(cur,"UPDATE hitl_events SET action='standing_approve',reviewer='system' WHERE item_id=%s",(item,))
    before=contribution.read_contribution(s,'owner','scan',run)
    assert before['outcomes']['fixed']==0
    tickets=contribution.writer_tickets(s,'scan','a.docx',[item],'a'*64,actual_values={'image':'A tree'})
    assert len(tickets)==1
    contribution.record_writer_result(s,tickets,outcome='verified_cleared',artifact_sha256='b'*64,
        reference='stored fixture artifact',writer_attempt_id='system-write')
    after=contribution.read_contribution(s,'owner','scan',run)
    assert after['outcomes']['fixed']==1
    assert after['findings'][0]['approval_kind']=='run_authorization'
