"""Real proposer -> paid-intent fixture -> trace -> exact contribution, no external calls."""
from dataclasses import replace
from hashlib import sha256
from types import MappingProxyType
import json

from test_llm_waterfall_provider import specs, FakeProviders, Response, result
from test_propose_slide_titles import _pptx, _slide
from ai_run_policy import RunContext, _CURRENT
from ai_spending_budget import BudgetLedger
from remediation_contribution import SOURCE, freeze_baseline, read_contribution
from remediation_run_insights import capture_proposals
from remediation_run_graph import read_run_graph
import llm_waterfall_provider as bounded


def test_two_files_third_model_proposals_are_two_findings_after_replay(isolated_store, tmp_path, monkeypatch, specs):
    import core
    import proposals
    store = isolated_store
    monkeypatch.setattr(core, 'store', store)
    specs = (*specs, replace(specs[1], model='third-pinned-v1'))
    chain = {'version': 1, 'steps': [dict(step_id=step,position=i,provider=s.provider,model=s.model,enabled=True,capabilities=['text'])
        for i,(step,s) in enumerate(zip(('primary','fallback_1','fallback_2'),specs))]}
    policy = dict(ai=1,rule_based=2,ai_budget_usd='5.00',generation_chain=chain)
    paths = []
    for i in range(2):
        directory = tmp_path / str(i)
        directory.mkdir()
        paths.append(_pptx(directory, [_slide('', f'Revenue growth for region {i} in this quarter')]))
    files = ['one.pptx', 'two.pptx']
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO scan_runs(id,owner_email,status) VALUES('scan','owner','done')")
    run = store.enqueue_stage_batch('scan','remediate','remediate_file',[
        dict(owner='owner',scan_id='scan',file=file,remediation_impact_policy=policy) for file in files],
        snapshot_id='assessed',request_fingerprint='fixture')['batch_id']
    with store._db.cursor() as cur:
        freeze_baseline(store._db,cur,'owner','scan',run,'assessed',[
            dict(finding_id=f'f{i}',file=file,rule_id='2.4.6',instance_key='sole-title') for i,file in enumerate(files)],files)
    calls=[]
    def post(*args,**kwargs):
        model=kwargs['json']['model']
        calls.append(model)
        # Assert the new intent/lineage was committed before the synthetic transport.
        with store._db.cursor() as cur:
            store._db.execute(cur,"SELECT result_json FROM ai_attempt_history WHERE owner_id='owner' AND run_id=%s AND model=%s AND status='started'",(run,model))
            retained=store._db.fetchall(cur)
        assert retained and all(json.loads(r['result_json'])['execution']['source_sha256'] for r in retained)
        text = '' if model==specs[0].model else 'Title: placeholder content' if model==specs[1].model else 'Quarterly Revenue Growth Overview'
        return Response(result(model=model,text=text))
    generator=bounded.StrictTextGenerator(specs,provider_module=FakeProviders,post=post)
    monkeypatch.setattr(bounded,'configured_generator',lambda:generator)
    for path,file in zip(paths,files):
        ctx=RunContext(BudgetLedger(store._db),'owner','scan',run,MappingProxyType({**policy,'cap_units':5_000_000}),file=file)
        token=_CURRENT.set(ctx)
        source_token=SOURCE.set(('scan',file,sha256(path.read_bytes()).hexdigest()))
        try:
            proposed=proposals.propose_slide_titles(path,'.pptx')
            assert len(proposed)==1
            assert proposed[0]['model']==specs[2].model
            assert proposed[0]['model_call_id']
            with store._db.cursor() as cur:
                capture_proposals(store._db,cur,ctx,scan_id='scan',file=file,rule_id='2.4.6',item_id=file,proposals=proposed)
            replay=proposals.propose_slide_titles(path,'.pptx')
            assert replay==proposed
        finally:
            SOURCE.reset(source_token)
            _CURRENT.reset(token)
    assert len(calls)==6
    assert BudgetLedger(store._db).snapshot('owner',run)['spent_units']==720
    contribution=read_contribution(store,'owner','scan',run)
    assert contribution['contributions']['fallback_2_ai']==2
    assert contribution['outcomes']['awaiting_review']==2
    assert contribution['outcomes']['fixed']==0
    graph=read_run_graph(store,'owner','scan',run)
    assert [s['model'] for s in graph['steps']]==[s.model for s in specs]
    assert graph['steps'][2]['state']=='suggestions_ready'
    assert len(graph['edges'])==4
