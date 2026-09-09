"""Explicit generation lineage fixtures; no production calibration claims."""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))
import remediation_contribution as c


def chain():
    result=[]
    for n in range(3):
        execution=dict(chain_version=1,step_id=('primary','fallback_1','fallback_2')[n],generation_position=n,
            parent_attempt_id=str(n-1) if n else None, escalation_reason='invalid_required_structure' if n else None,
            source_sha256='a'*64,assessment_revision='assessment',finding_ids=['f'],request_id=str(n),
            locator='slide 1',adapter_id='pptx-slide-title.v1')
        result.append(dict(owner_id='owner',scan_id='scan',run_id='run',file='deck.pptx',operation_id='op',input_sha256='b'*64,
            attempt_id=str(n),status='drafted' if n==2 else 'unusable_response',spending_state='settled',
            result_json=json.dumps(dict(execution=execution,validation_outcome='usable' if n==2 else 'invalid_required_structure'))))
    return result


def credit(rows):
    return c.chain_contribution(rows[-1],rows,source_sha256='a'*64,assessment_revision='assessment',finding_ids=['f'],locator='slide 1')


def test_two_exact_settled_eligible_parents():
    assert credit(chain()) == 'fallback_2_ai'


@pytest.mark.parametrize('key,value', [('source_sha256','c'*64),('assessment_revision','old'),('finding_ids',['other']),('parent_attempt_id','missing'),('request_id','wrong'),('escalation_reason','truncated'),('locator','slide 2')])
def test_changed_lineage_denies_credit(key,value):
    rows=chain(); result=json.loads(rows[1]['result_json']); result['execution'][key]=value
    rows[1]['result_json']=json.dumps(result)
    assert credit(rows) is None


@pytest.mark.parametrize('key,value',[('spending_state','uncertain'),('owner_id','other'),('input_sha256','c'*64),('operation_id','other')])
def test_unsettled_or_other_scope_parent_denies_credit(key,value):
    rows=chain();rows[0][key]=value
    assert credit(rows) is None


def test_usable_parent_cannot_be_escalated():
    rows=chain();r=json.loads(rows[1]['result_json']);r['validation_outcome']='usable';rows[1]['result_json']=json.dumps(r)
    assert credit(rows) is None


def test_five_findings_stay_five_across_second_fallback_revisions():
    baseline=dict(owner_id='owner',scan_id='scan',run_id='run',snapshot_id='assessment',files_json='["deck.pptx"]',baseline_json=json.dumps([
        dict(finding_id=str(i),file='deck.pptx',rule_id='2.4.6') for i in range(5)]))
    p=dict(owner_id='owner',scan_id='scan',run_id='run',proposal_id='p',proposal_sha256='d'*64,source_sha256='a'*64,
        finding_ids_json=json.dumps([str(i) for i in range(5)]),origin='fallback_2_ai')
    result=c.aggregate(baseline,[p,{**p,'proposal_id':'revision'}],[])
    assert result['contributions']['fallback_2_ai']==5
    assert result['outcomes']['awaiting_review']==5
    assert result['fallback_2_additional_findings']==5
