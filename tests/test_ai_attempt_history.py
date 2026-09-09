"""Real isolated ledger + synthetic HTTP: durable output and no paid replay."""
from hashlib import sha256

import pytest

from test_llm_waterfall_provider import managed, specs, Response, result
import llm_waterfall_provider as bounded
from ai_attempt_history import AttemptHistory, MAX_OUTPUT_BYTES
from ai_spending_budget import AttemptConflict


@pytest.fixture
def history(managed):
    managed.scan_id = 'scan'
    managed.file = 'report.docx'
    value = AttemptHistory(managed.ledger.db)
    value.init_schema()
    return value


def test_persists_both_actual_outputs_and_replays_fallback_without_spending(managed, history, monkeypatch):
    import httpx
    calls = []
    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        data = result(model=model, text='partial first draft' if len(calls) == 1 else '<b>Actual second draft</b>')
        data['choices'][0]['finish_reason'] = 'length' if len(calls) == 1 else 'stop'
        return Response(data)
    monkeypatch.setattr(httpx, 'post', post)
    generated = bounded.managed_text_generate('source prompt')
    rows = history.list_run('owner', 'scan', 'run')
    assert [r['purpose'] for r in rows] == ['draft', 'fallback']
    assert [r['status'] for r in rows] == ['unusable_response', 'drafted']
    assert [r['result']['text'] for r in rows] == ['partial first draft', '<b>Actual second draft</b>']
    assert all(r['spending_state'] == 'settled' for r in rows)
    assert all(r['input_sha256'] == sha256(b'source prompt').hexdigest() for r in rows)
    replay = bounded.managed_text_generate('source prompt')
    assert replay['replayed'] is True
    assert replay['text'] == generated['text']
    assert replay['approval_required'] is True
    assert len(calls) == 2
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 240


def test_history_owner_scan_file_scope_and_exact_trace_binding(managed, history, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: Response(result(text='retained draft')))
    generated = bounded.managed_text_generate('source prompt')
    assert history.list_run('other', 'scan', 'run') == []
    assert history.list_run('owner', 'other-scan', 'run') == []
    assert history.list_operation('owner', 'scan', 'run', generated['operation_id'], file='other.docx') == []
    assert history.bind_trace('owner','scan','run',generated['operation_id'],'trace-wrong',
                              file='report.docx',output_sha256=sha256(b'wrong').hexdigest()) is None
    attempt = history.bind_trace('owner','scan','run',generated['operation_id'],'trace-1',
                                 file='report.docx',output_sha256=sha256(b'retained draft').hexdigest())
    assert attempt == generated['history_attempt_id']
    history.bind_trace('owner','scan','run',generated['operation_id'],'trace-replay',
                       file='report.docx',output_sha256=sha256(b'retained draft').hexdigest())
    assert history.list_run('owner','scan','run')[0]['trace_call_ids'] == ['trace-1','trace-replay']


def test_completed_output_and_attempt_identity_are_immutable(managed, history, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: Response(result(text='original output')))
    generated = bounded.managed_text_generate('source prompt')
    row = history.list_run('owner','scan','run')[0]
    with pytest.raises(AttemptConflict):
        history.begin('owner','scan','run',row['operation_id'],row['attempt_id'],file='different.docx',
                      input_sha256=row['input_sha256'],model=row['model'],provider=row['provider'])
    with pytest.raises(AttemptConflict):
        history.finish('owner','scan','run',row['attempt_id'],status='drafted',
                       result={**row['result'],'text':'rewritten output'})
    assert history.list_run('owner','scan','run')[0]['result']['text'] == generated['text']


def test_size_limit_records_hash_and_explicit_missing_content(managed, history):
    digest = sha256(b'input').hexdigest()
    history.begin('owner','scan','run',digest,'oversized',file='report.docx',input_sha256=digest,
                  model='model',provider='openai')
    output = 'x' * (MAX_OUTPUT_BYTES + 1)
    row = history.finish('owner','scan','run','oversized',status='drafted',
                         result={'text':output,'model':'model','provider':'openai','secret':'not retained'})
    assert row['output_retention'] == 'omitted_size_limit'
    assert row['output_sha256'] == sha256(output.encode()).hexdigest()
    assert row['result']['text'] is None
    assert 'secret' not in row['result']


def test_persistence_failure_before_dispatch_does_not_call_or_hold_spend(managed, history, monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(httpx,'post',lambda *a,**kw: calls.append(kw))
    monkeypatch.setattr(AttemptHistory,'begin',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('write failed')))
    response = bounded.managed_text_generate('source prompt')
    assert response['reason'] == 'attempt_history_unavailable'
    assert calls == []
    snapshot = managed.ledger.snapshot('owner','run')
    assert snapshot['spent_units'] == snapshot['held_units'] == 0


def test_output_persistence_failure_never_buys_retry(managed, history, monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(httpx,'post',lambda *a,**kw: calls.append(kw) or Response(result(text='paid output')))
    monkeypatch.setattr(AttemptHistory,'finish',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('write failed')))
    assert bounded.managed_text_generate('source prompt')['reason'] == 'attempt_output_retention_failed'
    assert bounded.managed_text_generate('source prompt')['reason'] == 'existing_draft_attempt_requires_reconciliation'
    assert len(calls) == 1


def test_review_purpose_has_distinct_identity_and_only_requested_tier(managed, history, monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(httpx,'post',lambda *a,**kw: calls.append(kw['json']['model']) or Response(result(model=kw['json']['model'],text='review response')))
    generator = bounded.configured_generator()
    reviewed = bounded.managed_generate_attempts('source prompt',managed,generator,purpose='review',tier_indices=(2,))
    replay = bounded.managed_generate_attempts('source prompt',managed,generator,purpose='review',tier_indices=(2,))
    assert replay['replayed'] is True
    assert calls == ['large-pinned-v1']
    assert reviewed['operation_id'] != sha256(b'source prompt').hexdigest()
    assert history.list_run('owner','scan','run')[0]['purpose'] == 'review'


def test_retained_refusal_is_never_replayed_as_draft_or_escalated(managed, history, monkeypatch):
    import httpx
    calls = []
    def post(*a, **kw):
        calls.append(kw)
        data = result(text='Refusal explanation')
        data['choices'][0]['message']['refusal'] = 'Cannot comply'
        return Response(data)
    monkeypatch.setattr(httpx,'post',post)
    assert bounded.managed_text_generate('source prompt')['reason'] == 'provider_refused'
    assert bounded.managed_text_generate('source prompt')['reason'] == 'existing_draft_attempt_requires_reconciliation'
    rows = history.list_run('owner','scan','run')
    assert len(rows) == len(calls) == 1
    assert rows[0]['status'] == 'refused'
    assert rows[0]['result']['text'] == 'Refusal explanation'


def test_same_prompt_in_other_file_cannot_replay_or_purchase_duplicate(managed, history, monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(httpx,'post',lambda *a,**kw: calls.append(kw) or Response(result(text='file-specific output')))
    assert bounded.managed_text_generate('source prompt')['text'] == 'file-specific output'
    managed.file = 'other.docx'
    assert bounded.managed_text_generate('source prompt')['reason'] == 'attempt_history_unavailable'
    assert len(calls) == 1


@pytest.mark.parametrize('first_output,finish', [('', 'stop'), ('Incomplete draft', 'length')])
def test_worker_retry_resumes_after_retained_settled_unusable_first_tier(managed, history, monkeypatch, first_output, finish):
    import httpx
    calls = []
    def post(*a, **kw):
        model = kw['json']['model']
        calls.append(model)
        data = result(model=model,text=first_output if model == 'small-pinned-v1' else 'Complete fallback')
        data['choices'][0]['finish_reason'] = finish if model == 'small-pinned-v1' else 'stop'
        return Response(data)
    monkeypatch.setattr(httpx,'post',post)
    original_reserve = managed.ledger.reserve
    def interrupted(owner,run,attempt,*args,**kwargs):
        if ':2:' in attempt:
            raise KeyboardInterrupt('worker stopped before fallback dispatch')
        return original_reserve(owner,run,attempt,*args,**kwargs)
    monkeypatch.setattr(managed.ledger,'reserve',interrupted)
    with pytest.raises(KeyboardInterrupt):
        bounded.managed_text_generate('source prompt')
    assert len(calls) == 1
    assert history.list_run('owner','scan','run')[0]['spending_state'] == 'settled'
    monkeypatch.setattr(managed.ledger,'reserve',original_reserve)
    resumed = bounded.managed_text_generate('source prompt')
    assert resumed['text'] == 'Complete fallback'
    assert calls == ['small-pinned-v1','large-pinned-v1']
    assert len(resumed['attempts']) == 2
    assert managed.ledger.snapshot('owner','run')['spent_units'] == 240
