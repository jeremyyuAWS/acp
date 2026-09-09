import copy
import json
from datetime import datetime, timezone
import pytest
import store as store_module
from store import Store
from ai_review_calibration import (normalize_evaluation, ingest_evaluation, read_evaluation,
    applicable_evaluation, wilson_lower, load_calibration_records, ADMIN_KEY)
from ai_threshold_execution import seal_policy, evaluate_policy

NOW = datetime(2026,9,9,tzinfo=timezone.utc)
CONFIG = dict(format='html', change_family='fixture_objective', generator_provider='provider', generator_model='g1',
              reviewer_provider='provider', reviewer_model='r1', validator_version='v1')
RULE = dict(minimum_reliability=90, minimum_sample_size=100, freshness_days=30, writer_supported=True)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, '_SQLITE_PATH', str(tmp_path / 'test.db'))
    import ai_threshold_execution
    monkeypatch.setitem(ai_threshold_execution.SUPPORTED_WRITERS, 'fixture_objective', object())
    return Store()


def cohort(kind='evaluated'):
    return dict(schema_version='ai-review-calibration.v1', evaluation_version='fixture-v1',
        evaluated_at='2026-09-08T00:00:00Z', **CONFIG,
        provenance=dict(kind=kind,dataset_sha256='a'*64,evaluation_report_sha256='b'*64,
                        representative=True,production_approved=True,approval_ref='fixture-only-not-production',qualification_owner='owner'),
        samples=[dict(sample_id=str(i),passed=True,judgment_origin='objective_validator',evidence_ref='fixture:'+str(i)) for i in range(100)])


def prepare(db):
    db.set_setting(ADMIN_KEY,json.dumps({'schema_version':'ai-review-admin.v1','families':{'fixture_objective':RULE}}))
    ingest_evaluation(db,'owner',cohort())
    policy = seal_policy(db,'owner',dict(enabled=True,mode='threshold',minimum_reliability=95,
        permitted_families=['fixture_objective'],evaluation_versions={'fixture_objective':'fixture-v1'}),now=NOW)
    evidence = dict(change_family='fixture_objective',supported=True,proposal_sha256='proposal',
        snapshot_id='snapshot',source_sha256='source',current_source_sha256='source',configuration=CONFIG,
        review=dict(verdict='accept',proposal_sha256='proposal',source_sha256='source',independent=True,model='r1',provider='provider'),
        validation=dict(passed=True,objective=True,proposal_sha256='proposal',source_sha256='source',validator_version='v1'),
        source_evidence_complete=True,subjective=False,disagreement=False,hard_review_conditions=[])
    return policy,evidence


def test_ingestion_computes_bound_and_rejects_fabricated_counts():
    record=cohort()
    record.update(sample_size=100000,successes=100000,reliability_lower_bound=1)
    result=normalize_evaluation(record)
    assert result['sample_size']==100
    assert result['reliability_lower_bound']==pytest.approx(.9630065017930143)
    with pytest.raises(ValueError):
        normalize_evaluation({**record,'samples':record['samples']+[record['samples'][0]]})


@pytest.mark.parametrize('mutation', [lambda r:r.update(evaluated_at='2026-09-08'),
    lambda r:r['samples'][0].update(passed=1),lambda r:r['samples'][0].update(judgment_origin='model'),
    lambda r:r['provenance'].update(dataset_sha256=''),lambda r:r.update(samples=[])])
def test_invalid_evidence_rejected(mutation):
    value=cohort();mutation(value)
    with pytest.raises(ValueError):normalize_evaluation(value)


def test_versions_immutable_replay_and_owner_scoping(db):
    first=ingest_evaluation(db,'owner',cohort())
    assert ingest_evaluation(db,'owner',cohort())==first
    changed=cohort();changed['samples'][0]['passed']=False
    with pytest.raises(ValueError,match='immutable'):ingest_evaluation(db,'owner',changed)
    assert read_evaluation(db,'other','fixture-v1') is None
    assert load_calibration_records(db,'other')==[]
    assert load_calibration_records(db,'owner')==[first]


@pytest.mark.parametrize('kind,now,rule,config,reason',[
    ('synthetic',NOW,RULE,CONFIG,'synthetic_calibration_not_eligible'),
    ('evaluated',datetime(2026,11,1,tzinfo=timezone.utc),RULE,CONFIG,'calibration_expired_or_future'),
    ('evaluated',datetime(2026,9,1,tzinfo=timezone.utc),RULE,CONFIG,'calibration_expired_or_future'),
    ('evaluated',NOW,{**RULE,'minimum_sample_size':101},CONFIG,'calibration_sample_size_insufficient'),
    ('evaluated',NOW,RULE,{**CONFIG,'generator_model':'changed'},'calibration_configuration_mismatch')])
def test_calibration_applicability_hard_gates(db,kind,now,rule,config,reason):
    ingest_evaluation(db,'owner',cohort(kind))
    check=applicable_evaluation(db,'owner','fixture-v1',config,rule,now=now)
    assert check['available'] is False
    assert check['reason']==reason


@pytest.mark.parametrize('delta,requires',[(-.00001,True),(0,False),(.00001,False)])
def test_real_computed_boundary_below_equal_above(db,delta,requires):
    policy,evidence=prepare(db)
    lower=wilson_lower(100,100)*100
    policy['minimum_reliability']=lower-delta
    gate=evaluate_policy(db,'owner',policy,evidence,now=NOW)
    assert gate['approval_required'] is requires
    assert all(row['passed'] for row in gate['checks'][:-1])


@pytest.mark.parametrize('changed',[
    {'supported':False},{'current_source_sha256':'changed'},{'subjective':True},
    {'disagreement':True},{'source_evidence_complete':False},{'hard_review_conditions':['refusal']},
    {'snapshot_id':None},{'configuration':{**CONFIG,'validator_version':'changed'}},
    {'review':{}},{'validation':{}},{'hard_review_conditions':None}])
def test_every_gate_remains_human_reviewed_despite_high_reliability(db,changed):
    policy,evidence=prepare(db)
    assert evaluate_policy(db,'owner',policy,{**evidence,**changed},now=NOW)['approval_required']


def test_nested_review_and_validation_failures(db):
    policy,evidence=prepare(db)
    for key,changes in [('review',{'proposal_sha256':'old'}),('review',{'source_sha256':'old'}),
       ('review',{'independent':False}),('review',{'model':'g1'}),('review',{'verdict':'revise'}),
       ('validation',{'passed':False}),('validation',{'objective':False}),('validation',{'source_sha256':'old'})]:
        changed=copy.deepcopy(evidence);changed[key].update(changes)
        assert evaluate_policy(db,'owner',policy,changed,now=NOW)['approval_required']


def test_missing_and_expired_calibration_never_qualify(db):
    policy,evidence=prepare(db)
    assert evaluate_policy(db,'other',policy,evidence,now=NOW)['approval_required']
    assert evaluate_policy(db,'owner',policy,evidence,now=datetime(2027,1,1,tzinfo=timezone.utc))['approval_required']


def test_midrun_admin_loosen_cannot_broaden_snapshot_and_tighten_denies(db):
    policy,evidence=prepare(db)
    policy['minimum_reliability']=99
    db.set_setting(ADMIN_KEY,json.dumps({'schema_version':'ai-review-admin.v1','families':{'fixture_objective':{**RULE,'minimum_reliability':0}}}))
    assert evaluate_policy(db,'owner',policy,evidence,now=NOW)['approval_required']
    policy['minimum_reliability']=95
    db.set_setting(ADMIN_KEY,json.dumps({'schema_version':'ai-review-admin.v1','families':{'fixture_objective':{**RULE,'minimum_reliability':99}}}))
    assert evaluate_policy(db,'owner',policy,evidence,now=NOW)['approval_required']
    assert policy['families']['fixture_objective']['administrator']==RULE


def test_no_automatic_enablement_of_old_runs(db):
    _,evidence=prepare(db)
    assert evaluate_policy(db,'owner',None,evidence,now=NOW)['approval_required']
    assert seal_policy(db,'owner',{'mode':'review_all'}) is None


def test_registry_default_cannot_be_enabled_by_administrator_config(db,monkeypatch):
    from ai_threshold_execution import apply_under_run_policy
    prepare(db)
    from ai_threshold_execution import SUPPORTED_WRITERS
    monkeypatch.delitem(SUPPORTED_WRITERS,'fixture_objective')
    assert apply_under_run_policy(db,'owner','scan','run','snapshot','fixture_objective')['reason']=='supported_objective_writer_unavailable'


def test_controlled_adapter_replay_and_postwrite_verification(db,monkeypatch):
    import ai_threshold_execution as execution
    from types import SimpleNamespace
    policy,evidence=prepare(db)
    monkeypatch.setattr(execution,'read_run_policy',lambda *args:policy)
    calls=[]
    def apply(*args):
        calls.append(args[-1])
        assert args[-1]['status']=='approved_awaiting_completion'
        return dict(verified=True,snapshot_id='snapshot',proposal_sha256='proposal',source_sha256='source',
                    artifact_sha256='artifact',verification_ref='check')
    monkeypatch.setitem(execution.SUPPORTED_WRITERS,'fixture_objective',SimpleNamespace(prepare=lambda *args:evidence,apply=apply))
    first=execution.apply_under_run_policy(db,'owner','scan','run','snapshot','fixture_objective',now=NOW)
    assert first['status']=='fixed_and_checked'
    policy['minimum_reliability']=0
    replay=execution.apply_under_run_policy(db,'owner','scan','run','snapshot','fixture_objective',now=NOW)
    assert replay['replayed'] is True and replay['minimum_reliability']==95
    assert len(calls)==1


@pytest.mark.parametrize('outcome',[None, {'verified':True}, {'verified':False,'verification_ref':'failed'}])
def test_failed_verification_never_counts_approved_as_fixed(db,monkeypatch,outcome):
    import ai_threshold_execution as execution
    from types import SimpleNamespace
    policy,evidence=prepare(db)
    monkeypatch.setattr(execution,'read_run_policy',lambda *args:policy)
    monkeypatch.setitem(execution.SUPPORTED_WRITERS,'fixture_objective',SimpleNamespace(prepare=lambda *args:evidence,apply=lambda *args:outcome))
    assert execution.apply_under_run_policy(db,'owner','scan','run','snapshot','fixture_objective',now=NOW)['status']=='still_needs_work'


def test_source_change_between_gate_and_writer_stops_application(db,monkeypatch):
    import ai_threshold_execution as execution
    from types import SimpleNamespace
    policy,evidence=prepare(db)
    monkeypatch.setattr(execution,'read_run_policy',lambda *args:policy)
    inputs=iter([evidence,{**evidence,'current_source_sha256':'changed'}])
    monkeypatch.setitem(execution.SUPPORTED_WRITERS,'fixture_objective',SimpleNamespace(
        prepare=lambda *args:next(inputs),apply=lambda *args:pytest.fail('stale source was written')))
    result=execution.apply_under_run_policy(db,'owner','scan','run','snapshot','fixture_objective',now=NOW)
    assert result['approval_required'] and result['reason']=='evidence_changed_before_application'


def test_selection_has_no_invented_default_and_cannot_supply_approval_seal():
    from ai_threshold_execution import normalize_selection
    assert normalize_selection(None)['minimum_reliability'] is None
    assert normalize_selection(None)['mode']=='review_all'
    with pytest.raises(ValueError):normalize_selection({'threshold_policy':{'mode':'threshold'}})
    for value in (True,float('nan'),float('inf'),-1,101):
        with pytest.raises(ValueError):normalize_selection({'minimum_reliability':value})


def test_no_paid_preview_and_no_availability_without_registered_writer(db,monkeypatch):
    from ai_threshold_execution import capability_summary,SUPPORTED_WRITERS
    prepare(db)
    monkeypatch.delitem(SUPPORTED_WRITERS,'fixture_objective')
    result=capability_summary(db,'owner',now=NOW)
    assert result['automatic_application_supported'] is False
    assert result['administrator_floor'] is None
    assert result['eligible_families']==[]


def test_seal_changed_threshold_or_families_rejected(db):
    from ai_threshold_execution import normalize_sealed_policy
    policy,_=prepare(db)
    assert normalize_sealed_policy(policy)==policy
    with pytest.raises(ValueError):normalize_sealed_policy({**policy,'minimum_reliability':0})
    with pytest.raises(ValueError):normalize_sealed_policy({**policy,'families':{}})


def test_cli_default_only_validates_and_evaluated_ingest_requires_artifacts(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    script=Path(__file__).resolve().parents[1]/'scripts/ingest_ai_review_calibration.py'
    data=tmp_path/'evaluation.json';data.write_text(json.dumps(cohort('synthetic')))
    check=subprocess.run([sys.executable,str(script),str(data)],capture_output=True,text=True)
    assert check.returncode==0
    assert json.loads(check.stdout)['ingested'] is False
    data.write_text(json.dumps(cohort()))
    refused=subprocess.run([sys.executable,str(script),str(data),'--ingest','--owner','owner'],capture_output=True,text=True)
    assert refused.returncode==2
    assert 'requires --dataset and --report' in refused.stderr


def test_hashes_and_evaluated_label_do_not_establish_production_qualification(db):
    record=cohort()
    record['provenance'].pop('production_approved')
    ingest_evaluation(db,'owner',record)
    result=applicable_evaluation(db,'owner','fixture-v1',CONFIG,RULE,now=NOW)
    assert result['reason']=='calibration_production_approval_missing'
    assert result['available'] is False


def test_snapshot_pins_evaluation_and_cannot_be_replaced_midrun(db):
    from remediation_impact_settings import snapshot_impact_policy
    from ai_run_policy import normalize_run_policy, persist_run_policy
    from ai_spending_budget import AttemptConflict
    from ai_threshold_execution import read_run_policy
    policy,_=prepare(db)
    # Fixture current date is fixed to keep this test independent of wall-clock freshness.
    import ai_threshold_execution
    original=ai_threshold_execution.seal_policy
    from unittest.mock import patch
    selection=dict(rule_based=2,ai=1,ai_budget_usd='5.00',ai_review=dict(enabled=True,mode='threshold',minimum_reliability=95,
        permitted_families=['fixture_objective'],evaluation_versions={'fixture_objective':'fixture-v1'}))
    with patch.object(ai_threshold_execution,'seal_policy',side_effect=lambda s,o,p:original(s,o,p,now=NOW)):
        snapshot=snapshot_impact_policy(db,'owner',selection)
    normalized=normalize_run_policy(snapshot)
    assert normalized['threshold_policy']==policy
    with db._db.cursor() as cur:
        persist_run_policy(db._db,cur,'owner','scan','run',normalized)
    assert read_run_policy(db,'owner','scan','run')==policy
    assert read_run_policy(db,'other','scan','run') is None
    assert read_run_policy(db,'owner','other','run') is None
    changed=copy.deepcopy(normalized);changed['threshold_policy']['minimum_reliability']=0
    with pytest.raises(AttemptConflict), db._db.cursor() as cur:
        persist_run_policy(db._db,cur,'owner','scan','run',changed)
    assert read_run_policy(db,'owner','scan','run')==policy


def test_public_snapshot_cannot_inject_a_seal_or_enable_legacy_preference(db):
    from remediation_impact_settings import snapshot_impact_policy
    assert 'threshold_policy' not in snapshot_impact_policy(db,'owner',dict(rule_based=2,ai=1,ai_budget_usd='1.00',threshold_policy={'fake':True}))
    with pytest.raises(ValueError):
        snapshot_impact_policy(db,'owner',dict(rule_based=2,ai=1,ai_budget_usd='1.00',ai_review=dict(enabled=True,mode='threshold',minimum_reliability=95)))


def test_foreign_qualification_reference_cannot_be_ingested_as_own(db):
    foreign=cohort()
    foreign['provenance']['qualification_owner']='other'
    with pytest.raises(ValueError,match='does not belong'):
        ingest_evaluation(db,'owner',foreign)
    assert read_evaluation(db,'owner','fixture-v1') is None


def test_existing_accepted_run_keeps_pre_threshold_canonical_policy(db):
    from ai_run_policy import normalize_run_policy,persist_run_policy
    legacy_review={'enabled':True,'mode':'review_all','minimum_reliability':95,'max_review_attempts':1,'review_model':'strong'}
    legacy={'ai':1,'ai_budget_usd':'1.00','cap_units':1000000,'currency':'USD','ai_review':legacy_review}
    with db._db.cursor() as cur: persist_run_policy(db._db,cur,'owner','scan','legacy',legacy)
    normalized=normalize_run_policy({'ai':1,'ai_budget_usd':'1.00','ai_review':legacy_review})
    assert normalized==legacy
    with db._db.cursor() as cur: persist_run_policy(db._db,cur,'owner','scan','legacy',normalized)
    from ai_threshold_execution import read_run_policy
    assert read_run_policy(db,'owner','scan','legacy') is None


def test_shared_impact_evidence_is_normalized_in_the_same_immutable_owner_record(db):
    record=cohort()
    row=dict(finding_id='finding',source_revision='source',operation_id='op',evidence_id='evidence',
             observed_at='2026-09-07T00:00:00Z',rules_unresolved=True,usable=True)
    record['impact_evidence']=dict(schema_version='ai-impact-cohort.v1',representative=True,population_size=1,
        expires_at='2026-09-20T00:00:00Z',charges_complete=True,samples=[row,{**row,'prompt':'discard untrusted content'}],
        charges=[dict(charge_id='charge',operation_id='op',purpose='generation',status='settled',amount_usd='0.02')])
    saved=ingest_evaluation(db,'owner',record)
    assert len(saved['impact_evidence']['samples'])==1
    assert 'discard untrusted content' not in json.dumps(saved)
    assert read_evaluation(db,'owner','fixture-v1')==saved
    assert read_evaluation(db,'other','fixture-v1') is None
