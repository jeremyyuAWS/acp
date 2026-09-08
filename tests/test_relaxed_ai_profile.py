"""Relaxed profiles still require governance, accounting and complete responses."""
import pytest

from test_llm_waterfall_provider import managed, specs, Response, result
import llm_waterfall_provider as bounded


def test_incomplete_nonempty_draft_uses_second_attempt(managed, monkeypatch):
    import httpx
    calls = []
    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        data = result(model=model, text='Incomplete' if len(calls) == 1 else 'Annual report')
        data['choices'][0]['finish_reason'] = 'length' if len(calls) == 1 else 'stop'
        return Response(data)
    monkeypatch.setattr(httpx, 'post', post)
    draft = bounded.managed_text_generate('Name the linked report')
    assert calls == ['small-pinned-v1', 'large-pinned-v1']
    assert draft['text'] == 'Annual report'
    assert draft['approval_required'] is True
    assert draft['attempts'][0]['status'] == 'unusable_response'
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 240


@pytest.mark.parametrize('filtered', [False, True])
def test_explicit_refusal_is_not_an_approvable_draft(managed, monkeypatch, filtered):
    import httpx
    def post(*args, **kwargs):
        data = result(model=kwargs['json']['model'], text='Some output')
        if filtered:
            data['choices'][0]['finish_reason'] = 'content_filter'
        else:
            data['choices'][0]['message']['refusal'] = 'Cannot comply'
        return Response(data)
    monkeypatch.setattr(httpx, 'post', post)
    draft = bounded.managed_text_generate('Name the linked report')
    assert draft['deferred'] is True
    assert draft['reason'] == 'provider_refused'
    assert len(draft['attempts']) == 1
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 120


@pytest.mark.parametrize('profile,provider', [('openai-balanced', 'openai'),
                                           ('anthropic-balanced', 'anthropic')])
def test_profile_runs_both_models_with_real_ledger(managed, monkeypatch, profile, provider):
    import httpx
    import providers
    from ai_model_profiles import model_config
    config = model_config(profile)
    managed.ledger.create_budget('owner', 'relaxed', 25_000_000)
    managed.run_id = 'relaxed'
    monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON')
    monkeypatch.setenv('ACP_BOUNDED_TEXT_PROFILE', profile)
    monkeypatch.setattr(providers, 'active_text_provider', lambda: provider)
    calls = []
    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        if provider == 'openai':
            data = result(model=model, text='Partial' if len(calls) == 1 else 'Annual report')
            data['choices'][0]['finish_reason'] = 'length' if len(calls) == 1 else 'stop'
        else:
            data = {'model': model, 'id': 'fixture',
                    'usage': {'input_tokens': 100, 'output_tokens': 10},
                    'content': [{'type': 'text', 'text': 'Annual report'}],
                    'stop_reason': 'max_tokens' if len(calls) == 1 else 'end_turn'}
        return Response(data)
    monkeypatch.setattr(httpx, 'post', post)
    draft = providers.text_generate('Write a label')
    assert calls == [s['model'] for s in config]
    assert draft['text'] == 'Annual report'
    assert draft['approval_required'] is True
    budget = managed.ledger.snapshot('owner', 'relaxed')
    assert budget['held_units'] == 0
    assert budget['spent_units'] == (336 if provider == 'openai' else 450)


def test_profile_does_not_override_custom_config(managed, monkeypatch):
    monkeypatch.setenv('ACP_BOUNDED_TEXT_PROFILE', 'unknown')
    assert bounded.configured_generator().models[0].name == 'small-pinned-v1'


@pytest.mark.parametrize('kind', ['unknown', 'expired', 'wrong-provider'])
def test_bad_profile_never_dispatches(managed, monkeypatch, kind):
    import httpx
    from ai_model_profiles import VERIFIED_UNTIL
    monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON')
    monkeypatch.setenv('ACP_BOUNDED_TEXT_PROFILE',
        {'unknown': 'unknown', 'expired': 'openai-balanced',
         'wrong-provider': 'anthropic-balanced'}[kind])
    if kind == 'expired':
        monkeypatch.setattr(bounded, 'configured_generator', lambda: bounded.StrictTextGenerator(
            tuple(bounded.TextModelSpec(**s) for s in __import__('ai_model_profiles').model_config('openai-balanced')),
            clock=lambda: VERIFIED_UNTIL))
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert bounded.managed_text_generate('Draft')['reason'] == 'verified_model_pricing_unavailable'
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 0


def test_relaxed_profile_cannot_exceed_small_run_budget(managed, monkeypatch):
    import httpx
    monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON')
    monkeypatch.setenv('ACP_BOUNDED_TEXT_PROFILE', 'openai-balanced')
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert bounded.managed_text_generate('Draft')['reason'] == 'budget_admission_denied'
    assert managed.ledger.snapshot('owner', 'run')['held_units'] == 0
