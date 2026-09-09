"""Actual managed suggestion + trace storage, synthetic transport and local DB."""
from dataclasses import asdict
from hashlib import sha256
import json
import time

import pytest

from ai_run_policy import run_context
from ai_attempt_history import AttemptHistory
from test_ai_run_policy import seed, enqueue
from test_llm_waterfall_provider import specs, FakeProviders, Response, result


@pytest.fixture
def prepared(isolated_store, monkeypatch, specs):
    import core
    import providers
    import lf
    import httpx
    seed(isolated_store)
    batch = enqueue(isolated_store)
    job = isolated_store.get_job(batch['job_ids'][0])
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(providers, 'active_text_provider', FakeProviders.active_text_provider)
    monkeypatch.setattr(providers, '_text_key_for', FakeProviders._text_key_for)
    monkeypatch.setattr(lf, 'trace_ai_call', lambda *a, **kw: None)
    monkeypatch.setenv('ACP_BOUNDED_TEXT_MODELS_JSON', json.dumps([asdict(spec) for spec in specs]))
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs['json']['model'])
        return Response(result(model=kwargs['json']['model'], text=' "Useful report"\n'))
    monkeypatch.setattr(httpx, 'post', post)
    return isolated_store, job, calls


def suggest():
    import ai
    return ai.suggest_fix('2.4.4', 'Link purpose', 'A', 'a.html',
                          detail='The link says click here.', scan_id='scan', file='a.html')


def test_normalized_suggestion_links_raw_output_and_replay_records_only_one_charge(prepared):
    store, job, calls = prepared
    with run_context(store, job['payload'], job) as ctx:
        first = suggest()
        replay = suggest()
        history = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert first['suggestion'] == replay['suggestion'] == 'Useful report'
    assert first['ai_call_id'] == replay['ai_call_id']
    assert len(calls) == 1
    assert len(history) == 1
    assert history[0]['result']['text'] == ' "Useful report"\n'
    assert history[0]['trace_call_ids'] == [first['ai_call_id']]
    ledger = store.list_ai_calls('scan')
    assert len(ledger) == 1
    assert ledger[0]['cost_usd'] == pytest.approx(0.00012)
    assert ledger[0]['model'] == 'small-pinned-v1'


def test_replay_after_trace_link_write_failure_uses_same_durable_call_identity(prepared, monkeypatch):
    store, job, calls = prepared
    # The trace commits, then a crash/write failure prevents the separate link.
    # The next worker must not book that same paid model call a second time.
    monkeypatch.setattr(AttemptHistory, 'bind_trace', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('link unavailable')))
    with run_context(store, job['payload'], job):
        first = suggest()
        replay = suggest()
    assert first['ai_call_id'] == replay['ai_call_id']
    assert len(calls) == 1
    assert len(store.list_ai_calls('scan')) == 1


@pytest.mark.parametrize('field,value', [('model','different-model'), ('provider','different-provider')])
def test_trace_does_not_bind_same_output_to_a_different_recorded_model(prepared, field, value):
    import ai
    import providers
    store, job, _ = prepared
    with run_context(store, job['payload'], job) as ctx:
        prompt = 'A task with source'
        generated = providers.text_generate(prompt)
        identity = {'model': generated['model'], 'provider': generated['provider'], field: value}
        trace = ai._trace_ai('suggest', prompt, generated['text'], time.monotonic(), ok=True,
            **identity, zone=generated['zone'],
            cost_usd=generated['cost_usd'], scan_id='scan', file='a.html',
            managed_output_sha256=sha256(generated['text'].encode()).hexdigest())
        history = AttemptHistory(store._db).list_run(ctx.owner_id,ctx.scan_id,ctx.run_id)
    assert trace is not None
    assert history[0]['trace_call_ids'] == []


@pytest.mark.parametrize('field,value', [('file','other.html'), ('scan_id','other-scan'), ('cost_usd',0.2), ('model','other-model')])
def test_durable_call_identity_cannot_be_reused_for_other_scope_or_charge(prepared, field, value):
    store, _, _ = prepared
    original = dict(surface='suggest',provider='openai',model='fixture',zone='cloud',
                    latency_ms=1,ok=True,cost_usd=0.01,scan_id='scan',file='a.html',call_identity='durable-call')
    store.record_ai_call(**original)
    with pytest.raises(ValueError):
        store.record_ai_call(**{**original,field:value})
    [saved] = store.list_ai_calls('scan')
    assert saved['file'] == 'a.html'
    assert saved['cost_usd'] == 0.01
