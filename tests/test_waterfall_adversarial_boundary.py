"""Boundary cases use synthetic prices, isolated SQLite, and mocked HTTP only."""
from dataclasses import asdict, replace
import json

import pytest

from test_llm_waterfall_provider import managed, specs, Response, result
import llm_waterfall_provider as bounded


@pytest.mark.parametrize('first_issue', ['empty', 'truncated'])
def test_budget_exhausted_between_tiers_never_dispatches_second(managed, monkeypatch, first_issue):
    import httpx
    # First reservation fits exactly; its measured spend leaves insufficient
    # capacity for a second maximum-cost reservation.
    managed.ledger.create_budget('owner', 'tight', 8448)
    managed.run_id = 'tight'
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs['json']['model'])
        data = result(text='' if first_issue == 'empty' else 'Partial draft')
        data['choices'][0]['finish_reason'] = 'length' if first_issue == 'truncated' else 'stop'
        return Response(data)

    monkeypatch.setattr(httpx, 'post', post)
    draft = bounded.managed_text_generate('Describe the report')
    assert draft['reason'] == 'budget_admission_denied'
    assert not draft.get('text')
    assert calls == ['small-pinned-v1']
    snapshot = managed.ledger.snapshot('owner', 'tight')
    assert snapshot['spent_units'] == 120
    assert snapshot['held_units'] == 0
    replay = bounded.managed_text_generate('Describe the report')
    assert replay['reason'] == 'existing_draft_attempt_requires_reconciliation'
    assert calls == ['small-pinned-v1']


def test_both_models_truncated_never_return_partial_draft(managed, monkeypatch):
    import httpx
    calls = []

    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        data = result(model=model, text='Plausible but incomplete draft')
        data['choices'][0]['finish_reason'] = 'length'
        return Response(data)

    monkeypatch.setattr(httpx, 'post', post)
    draft = bounded.managed_text_generate('Write descriptive text')
    assert draft['reason'] == 'attempts_exhausted'
    assert not draft.get('text')
    assert calls == ['small-pinned-v1', 'large-pinned-v1']
    assert all(a['reason'] == 'truncated' for a in draft['attempts'])
    snapshot = managed.ledger.snapshot('owner', 'run')
    assert snapshot['spent_units'] == 240
    assert snapshot['held_units'] == 0


def test_anthropic_refusal_accounts_cost_and_stops_escalation(managed, specs, monkeypatch):
    import httpx
    import providers
    monkeypatch.setattr(providers, 'active_text_provider', lambda: 'anthropic')
    monkeypatch.setenv('ACP_BOUNDED_TEXT_MODELS_JSON', json.dumps([
        asdict(replace(s, provider='anthropic')) for s in specs]))
    calls = []

    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        return Response({'model': model, 'id': 'fixture-refusal',
                         'usage': {'input_tokens': 100, 'output_tokens': 10},
                         'content': [{'type': 'text', 'text': 'Refusal explanation'}],
                         'stop_reason': 'refusal'})

    monkeypatch.setattr(httpx, 'post', post)
    draft = bounded.managed_text_generate('Write descriptive text')
    assert draft['reason'] == 'provider_refused'
    assert not draft.get('text')
    assert calls == ['small-pinned-v1']
    snapshot = managed.ledger.snapshot('owner', 'run')
    assert snapshot['spent_units'] == 120
    assert snapshot['held_units'] == 0
