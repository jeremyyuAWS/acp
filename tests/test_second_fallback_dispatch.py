"""Synthetic HTTP + real durable budget/history; never production evaluation evidence."""
import json
import time
from types import SimpleNamespace
import pytest
import llm_waterfall_provider as provider
from ai_attempt_history import AttemptHistory
from ai_spending_budget import BudgetLedger
from ai_generation_adapter import generation_adapter, validate_slide_title
from remediation_contribution import SOURCE
from test_llm_waterfall_provider import FakeProviders, Response, result
from test_remediation_waterfall_view import seed

TITLE = 'Quarterly Revenue Growth Results'


@pytest.fixture
def dispatch(isolated_store, monkeypatch):
    store=isolated_store
    run=seed(store)
    specs=tuple(provider.TextModelSpec('openai',name,'fixture-price-v1','1','2',100000,128,int(time.time())+3600)
                for name in ('primary-v1','fallback-one-v1','fallback-two-v1'))
    steps=[dict(step_id=('primary','fallback_1','fallback_2')[i],position=i,provider='openai',model=s.model,
                enabled=True,capabilities=['text']) for i,s in enumerate(specs)]
    ctx=SimpleNamespace(ledger=BudgetLedger(store._db),owner_id='owner',scan_id='scan',run_id=run,file='a.html',
        enabled=True,deferred=[],policy={'generation_chain':{'version':1,'steps':steps}})
    monkeypatch.setattr(provider,'managed_context',lambda:ctx)
    binding=dict(adapter_id='pptx-slide-title.v1',source_sha256='a'*64,assessment_revision='snapshot',
                 finding_ids=['fixture-finding'],locator='slide 1',validator=validate_slide_title)
    calls=[]
    state=SimpleNamespace(ctx=ctx,store=store,binding=binding,calls=calls,responses=[],hook=None)
    def post(*args, **kwargs):
        model=kwargs['json']['model'];calls.append(model)
        # The durable execution identity must exist before a chargeable request.
        with store._db.cursor() as cur:
            store._db.execute(cur,"SELECT * FROM ai_attempt_history WHERE owner_id=%s AND run_id=%s AND status='started'",('owner',run))
            rows=store._db.fetchall(cur)
        assert len(rows)==1
        execution=json.loads(rows[0]['result_json'])['execution']
        assert execution['request_id']==rows[0]['attempt_id']
        assert execution['source_sha256']==binding['source_sha256']
        assert execution['finding_ids']==binding['finding_ids']
        assert execution['generation_position']==specs.index(next(s for s in specs if s.model==model))
        if state.hook: state.hook(state, execution)
        response=state.responses.pop(0)
        if isinstance(response, Exception): raise response
        payload=result(model=model,text=response) if isinstance(response,str) else {**response,'model':model}
        return Response(payload)
    state.generator=provider.StrictTextGenerator(specs,provider_module=FakeProviders,post=post)
    def invoke(prompt='Name the slide in three to eight words'):
        with generation_adapter(binding):
            return provider.managed_generate_attempts(prompt,ctx,state.generator)
    state.invoke=invoke
    state.history=lambda:AttemptHistory(store._db).list_run('owner','scan',run)
    token=SOURCE.set(('scan','a.html','a'*64))
    yield state
    SOURCE.reset(token)


@pytest.mark.parametrize('responses,expected', [([TITLE],1),(['',TITLE],2),(['','Title: Needs Revision',TITLE],3),(['Too Short','',TITLE],3)])
def test_stops_at_first_structurally_usable_title(dispatch,responses,expected):
    dispatch.responses=list(responses)
    output=dispatch.invoke()
    assert output.get('text')==TITLE, output
    assert output['approval_required'] is True
    assert len(dispatch.calls)==expected
    rows=dispatch.history()
    assert len(rows)==expected
    assert rows[-1]['result']['validation_outcome']=='usable'
    for index,row in enumerate(rows):
        execution=row['result']['execution']
        assert execution['generation_position']==index
        assert execution['parent_attempt_id']==(rows[index-1]['attempt_id'] if index else None)
    assert dispatch.ctx.ledger.snapshot('owner',dispatch.ctx.run_id)['spent_units']==120*expected


def test_third_result_exact_replay_does_not_charge(dispatch):
    dispatch.responses=['','',TITLE]
    first=dispatch.invoke()
    assert first.get('text')==TITLE, first
    before=dispatch.ctx.ledger.snapshot('owner',dispatch.ctx.run_id)
    replay=dispatch.invoke()
    assert replay['replayed'] is True
    assert replay['history_attempt_id']==first['history_attempt_id']
    assert len(dispatch.calls)==3
    assert dispatch.ctx.ledger.snapshot('owner',dispatch.ctx.run_id)==before


@pytest.mark.parametrize('response,reason',[
    (result(choices=[{'message':{'content':'','refusal':'Declined'}}]),'provider_refused'),
    (result(usage=None),'provider_usage_unknown'),
    (RuntimeError('fixture transport interruption'),'provider_usage_unknown'),
    (result(usage={'prompt_tokens':100,'completion_tokens':129}),'provider_limit_exceeded'),
])
def test_unsafe_response_does_not_fallback(dispatch,response,reason):
    dispatch.responses=[response]
    output=dispatch.invoke()
    assert output['reason']==reason
    assert len(dispatch.calls)==1
    assert len(dispatch.history())==1


def test_retry_resumes_two_settled_failures_after_budget_interruption(dispatch):
    dispatch.responses=['','',TITLE]
    ledger=dispatch.ctx.ledger
    def reserve_competing_work(state,execution):
        if execution['generation_position']==1:
            available=ledger.snapshot('owner',state.ctx.run_id)['available_units']
            ledger.reserve('owner',state.ctx.run_id,'competing-work',available,'fixture-price-v1')
    dispatch.hook=reserve_competing_work
    first=dispatch.invoke()
    assert first['reason']=='budget_admission_denied'
    assert len(dispatch.calls)==2
    ledger.release('owner',dispatch.ctx.run_id,'competing-work',confirmed_not_charged=True)
    dispatch.hook=None
    final=dispatch.invoke()
    assert final.get('text')==TITLE,final
    assert dispatch.calls==['primary-v1','fallback-one-v1','fallback-two-v1']
    assert len(dispatch.history())==3


@pytest.mark.parametrize('blocker',['source','cancel','provider'])
def test_permission_change_between_steps_blocks_fallback(dispatch,monkeypatch,blocker):
    dispatch.responses=['']
    def hook(state,execution):
        if blocker=='source': SOURCE.set(('scan','a.html','b'*64))
        elif blocker=='provider': monkeypatch.setattr(FakeProviders,'selected','anthropic')
        else:
            with state.store._db.cursor() as cur:
                state.store._db.execute(cur,"UPDATE stage_executions SET cancel_requested_at='fixture' WHERE execution_id=%s",(state.ctx.run_id,))
    dispatch.hook=hook
    output=dispatch.invoke()
    assert output['reason'] in ('assessed_source_changed','run_stopped_or_unavailable','request_rejected_before_dispatch')
    assert len(dispatch.calls)==1


def test_no_budget_never_dispatches(dispatch):
    dispatch.ctx.ledger.reserve('owner',dispatch.ctx.run_id,'competing-work',5_000_000,'fixture-price-v1')
    assert dispatch.invoke()['reason']=='budget_admission_denied'
    assert not dispatch.calls


def test_changed_binding_does_not_replay_prior_result(dispatch):
    dispatch.responses=[TITLE,TITLE]
    first=dispatch.invoke()
    dispatch.binding['finding_ids']=['different-finding']
    second=dispatch.invoke()
    assert second['history_attempt_id']!=first['history_attempt_id']
    assert not second.get('replayed')
    assert len(dispatch.calls)==2


def test_execution_lineage_cannot_be_mutated_after_dispatch(dispatch):
    dispatch.responses=[TITLE]
    output=dispatch.invoke()
    row=dispatch.history()[0]
    changed={**row['result'],'execution':{**row['result']['execution'],'finding_ids':['other']}}
    with pytest.raises(Exception,match='immutable'):
        AttemptHistory(dispatch.store._db).finish('owner','scan',dispatch.ctx.run_id,output['history_attempt_id'],status='drafted',result=changed)


def test_truncated_accounted_outputs_escalate_but_stop_after_three(dispatch):
    truncated=result(text='An incomplete title',choices=[{'message':{'content':'An incomplete title'},'finish_reason':'length'}])
    dispatch.responses=[truncated,truncated,truncated]
    output=dispatch.invoke()
    assert output['reason']=='attempts_exhausted'
    assert len(dispatch.calls)==3
    assert [r['result']['validation_outcome'] for r in dispatch.history()]==['truncated']*3
    assert dispatch.ctx.ledger.snapshot('owner',dispatch.ctx.run_id)['spent_units']==360


def test_missing_adapter_does_not_dispatch(dispatch):
    with generation_adapter(None):
        output=provider.managed_generate_attempts('Draft a title',dispatch.ctx,dispatch.generator)
    assert output['reason']=='supported_generation_adapter_required'
    assert not dispatch.calls


def test_stale_source_before_any_dispatch(dispatch):
    SOURCE.set(('scan','a.html','b'*64))
    assert dispatch.invoke()['reason']=='assessed_source_changed'
    assert not dispatch.calls


def test_unknown_charge_retry_never_rebuys_or_falls_back(dispatch):
    dispatch.responses=[RuntimeError('lost usage response')]
    first=dispatch.invoke()
    second=dispatch.invoke()
    assert first['reason']=='provider_usage_unknown'
    assert second['deferred'] is True
    assert len(dispatch.calls)==1
    assert dispatch.ctx.ledger.snapshot('owner',dispatch.ctx.run_id)['blocked'] is True
    assert dispatch.history()[0]['spending_state']=='uncertain'
