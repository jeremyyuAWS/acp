"""Structural drafting fixtures, not semantic review or production calibration."""
import sys
from pathlib import Path
from types import SimpleNamespace
from hashlib import sha256
import json
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
import ai_generation_adapter as a


@pytest.mark.parametrize('text', ['Quarterly Revenue Growth Results', 'Customer Support Response Times', 'A Better Product Roadmap'])
def test_valid_title(text):
    assert a.validate_slide_title(text) is None


@pytest.mark.parametrize('text', ['', 'Revenue', 'Title: Quarterly Revenue Growth', 'Here is your title', 'Insert Your Title Here', 'Quarterly\nRevenue Growth', 'A B C D E F G H I', '"Quarterly Revenue Growth"', '<b>Quarterly Revenue Growth</b>', 'Quarterly Revenue Growth\x00', 'Quarterly Revenue Growth '])
def test_invalid_title(text):
    assert a.validate_slide_title(text) in ('incomplete_requested_content', 'invalid_required_structure')


def test_context_reset_on_failure():
    assert a.current_generation_adapter() is None
    with pytest.raises(RuntimeError), a.generation_adapter({'locator':'slide 1'}):
        assert a.current_generation_adapter()['locator'] == 'slide 1'
        raise RuntimeError()
    assert a.current_generation_adapter() is None


@pytest.fixture
def bound(monkeypatch, tmp_path):
    import store as st
    import ai_run_policy as policy
    import remediation_contribution as c
    monkeypatch.setattr(st, '_SQLITE_PATH', tmp_path/'adapter.db')
    store = st.Store()
    path = tmp_path/'deck.pptx'; path.write_bytes(b'assessed fixture')
    with store._db.cursor() as cur:
        c.freeze_baseline(store._db, cur, 'owner', 'scan', 'run', 'assessment',
                          [dict(finding_id='f', file='deck.pptx', rule_id='2.4.6', instance_key='one')], ['deck.pptx'])
    ctx = SimpleNamespace(owner_id='owner',scan_id='scan',run_id='run',file='deck.pptx',policy={'generation_chain': {'version':1}},ledger=SimpleNamespace(db=store._db))
    monkeypatch.setattr(policy, 'optional_current_run_context', lambda:ctx)
    token = c.SOURCE.set(('scan','deck.pptx',sha256(path.read_bytes()).hexdigest()))
    yield path,ctx
    c.SOURCE.reset(token)


def test_exact_binding_and_ambiguity(bound):
    path,ctx = bound
    binding = a.slide_title_context(path,'slide 1',empty_count=1)
    assert binding['finding_ids'] == ['f']
    assert binding['assessment_revision'] == 'assessment'
    assert a.slide_title_context(path,'slide 1',empty_count=2) is None
    ctx.owner_id='other'
    assert a.slide_title_context(path,'slide 1',empty_count=1) is None


def test_stale_source_not_bound(bound):
    path,ctx=bound
    path.write_bytes(b'new document')
    assert a.slide_title_context(path,'slide 1',empty_count=1) is None


def test_proposer_scopes_context_and_preserves_trace(bound, monkeypatch, tmp_path):
    import ai
    import proposals
    import remediation_contribution as c
    from test_propose_slide_titles import _pptx, _slide
    path,ctx=bound
    path=_pptx(tmp_path,[_slide('', 'Quarterly revenue grew in every region')])
    token=c.SOURCE.set(('scan','deck.pptx',sha256(path.read_bytes()).hexdigest()))
    seen=[]
    def suggest(*args, **kwargs):
        seen.append(a.current_generation_adapter())
        return dict(suggestion='Quarterly Revenue Growth Results',model='model',call_id='trace')
    monkeypatch.setattr(ai,'model_is_available',lambda:True)
    monkeypatch.setattr(ai,'suggest_fix',suggest)
    try:
        output=proposals.propose_slide_titles(path,'pptx')
        assert seen[0]['finding_ids']==['f']
        assert output[0]['model_call_id']=='trace'
        assert output[0]['model']=='model'
        assert output[0]['baseline_finding_ids']==['f']
        assert a.current_generation_adapter() is None
        # Legacy runs retain existing title drafting behavior.
        ctx.policy={}
        monkeypatch.setattr(ai,'suggest_fix',lambda *a,**k:dict(suggestion='Revenue',model='model'))
        assert proposals.propose_slide_titles(path,'pptx')[0]['proposed_value']=='Revenue'
    finally:
        c.SOURCE.reset(token)


def test_bodyless_empty_slide_prevents_ambiguous_binding(bound, monkeypatch, tmp_path):
    import ai
    import proposals
    import remediation_contribution as c
    from test_propose_slide_titles import _pptx, _slide
    path,ctx=bound
    path=_pptx(tmp_path,[_slide('', 'Quarterly revenue grew'), _slide('', '')])
    token=c.SOURCE.set(('scan','deck.pptx',sha256(path.read_bytes()).hexdigest()))
    def suggest(*args, **kwargs):
        assert a.current_generation_adapter() is None
        return None
    monkeypatch.setattr(ai,'model_is_available',lambda:True)
    monkeypatch.setattr(ai,'suggest_fix',suggest)
    try:
        assert proposals.propose_slide_titles(path,'pptx')==[]
    finally:
        c.SOURCE.reset(token)
