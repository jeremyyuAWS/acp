"""Synthetic prices, mocked HTTP, and local SQLite only."""
from dataclasses import asdict, replace
import json
from types import SimpleNamespace
import time

import pytest

import llm_waterfall_provider as bounded
from llm_waterfall_provider import StrictTextGenerator, TextModelSpec
from llm_remediation_waterfall import Request


@pytest.fixture
def specs():
    return tuple(TextModelSpec('openai', name, 'fixture-price-v1', '1', '2', 8192, 128,
        int(time.time()) + 3600) for name in ('small-pinned-v1', 'large-pinned-v1'))


class FakeProviders:
    _OPENAI_TEXT_BASE_URL = 'https://fixture.invalid/v1'
    _ANTHROPIC_MESSAGES_URL = 'https://fixture.invalid/messages'
    _ANTHROPIC_API_VERSION = 'fixture'
    selected = 'openai'
    @classmethod
    def active_text_provider(cls):
        return cls.selected
    @staticmethod
    def _text_key_for(provider):
        return 'fixture-not-a-secret'
    @staticmethod
    def zone_for_url(url):
        return 'fixture'


class Response:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self.data


def result(model='small-pinned-v1', text='{"language":"en"}', **overrides):
    return {'model': model, 'id': 'fixture-call', 'usage': {'prompt_tokens': 100, 'completion_tokens': 10},
            'choices': [{'message': {'content': text}}], **overrides}


def test_strict_transport_one_request_and_exact_usage(specs):
    calls = []
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: calls.append((a, kw)) or Response(result()))
    generated = generator('small-pinned-v1', Request('op', '<html>Hi</html>',
        'html-root-language', 'auto', True, 'en', 'metadata:1'))
    assert generated.cost_usd == '0.00012'
    assert generated.patch == {'language': 'en'}
    assert len(calls) == 1
    assert calls[0][1]['json']['max_completion_tokens'] == 128
    assert calls[0][1]['follow_redirects'] is False
    assert generator.models[0].max_cost_usd == '0.008448'


@pytest.mark.parametrize('changes', [
    {'verified_until': 1}, {'input_usd_per_million': '0'},
    {'output_usd_per_million': 'NaN'}, {'context_token_limit': True},
    {'output_token_limit': 9000}, {'timeout_seconds': 121}, {'pricing_ref': ''},
])
def test_invalid_pricing_or_limits_never_dispatch(specs, changes):
    with pytest.raises(ValueError):
        StrictTextGenerator((replace(specs[0], **changes), specs[1]), provider_module=FakeProviders,
            post=lambda *a, **kw: pytest.fail('unexpected request'))


@pytest.mark.parametrize('data', [result(model='unexpected-alias'), result(usage=None),
    result(usage={'prompt_tokens': 1}), result(usage={'prompt_tokens': 0, 'completion_tokens': 2}),
    result(usage={'prompt_tokens': True, 'completion_tokens': 2})])
def test_missing_or_untrusted_usage_does_not_become_zero(specs, data):
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: Response(data))
    with pytest.raises(ValueError):
        generator.generate_text(specs[0].model, 'prompt')


def test_prompt_size_blocks_request(specs):
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: pytest.fail('unexpected request'))
    with pytest.raises(ValueError, match='size'):
        generator.generate_text(specs[0].model, 'x' * 9000)


def test_governance_change_blocks_request(specs, monkeypatch):
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: pytest.fail('unexpected request'))
    monkeypatch.setattr(FakeProviders, 'selected', 'anthropic')
    with pytest.raises(ValueError, match='governance'):
        generator.generate_text(specs[0].model, 'prompt')


@pytest.fixture
def managed(tmp_path, monkeypatch, specs):
    spending = pytest.importorskip('ai_spending_budget')
    from store import _SQLiteAdapter
    ledger = spending.BudgetLedger(_SQLiteAdapter(str(tmp_path / 'budget.db')))
    ledger.init_schema()
    ledger.create_budget('owner', 'run', 100_000)
    ctx = SimpleNamespace(ledger=ledger, owner_id='owner', run_id='run', enabled=True, deferred=[])
    monkeypatch.setattr(bounded, 'managed_context', lambda: ctx)
    monkeypatch.setenv('ACP_BOUNDED_TEXT_MODELS_JSON', json.dumps([asdict(s) for s in specs]))
    import providers
    monkeypatch.setattr(providers, 'active_text_provider', FakeProviders.active_text_provider)
    monkeypatch.setattr(providers, '_text_key_for', FakeProviders._text_key_for)
    return ctx


def test_existing_text_draft_is_bounded_and_needs_approval(managed, monkeypatch):
    import httpx
    import providers
    calls = []
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: calls.append(kw) or Response(result(text='Useful link text')))
    draft = providers.text_generate('Write link text')
    assert draft['text'] == 'Useful link text'
    assert draft['approval_required'] is True
    assert len(calls) == 1
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 120
    assert draft['attempts'][0]['status'] == 'drafted'


def test_empty_accounted_draft_falls_back_once(managed, monkeypatch):
    import httpx
    import providers
    calls = []
    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        return Response(result(model=model, text='' if len(calls) == 1 else 'Useful text'))
    monkeypatch.setattr(httpx, 'post', post)
    draft = providers.text_generate('Write link text')
    assert draft['text'] == 'Useful text'
    assert calls == ['small-pinned-v1', 'large-pinned-v1']
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 240


def test_timeout_blocks_fallback_and_keeps_hold(managed, monkeypatch):
    import httpx
    import providers
    calls = []
    def post(*a, **kw):
        calls.append(1)
        raise httpx.ReadTimeout('fixture')
    monkeypatch.setattr(httpx, 'post', post)
    draft = providers.text_generate('Write link text')
    assert draft['reason'] == 'provider_usage_unknown'
    assert calls == [1]
    snapshot = managed.ledger.snapshot('owner', 'run')
    assert snapshot['held_units'] == 8448
    assert snapshot['blocked']
    assert managed.deferred[-1]['reason'] == 'provider_usage_unknown'


@pytest.mark.parametrize('kind', ['disabled', 'missing-prices'])
def test_governance_failure_defers_without_request(managed, monkeypatch, kind):
    import httpx
    import providers
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    if kind == 'disabled':
        managed.enabled = False
    else:
        monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON')
    assert providers.text_generate('prompt')['deferred']
    assert managed.ledger.snapshot('owner', 'run')['held_units'] == 0


def test_all_vision_adapters_defer_before_network(managed, monkeypatch):
    import httpx
    import providers
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    for name in ('OllamaVisionProvider', 'AzureOpenAIVisionProvider', 'OpenAIVisionProvider',
        'GeminiVisionProvider', 'BedrockVisionProvider', 'AnthropicVisionProvider',
        'RunPodServerlessVisionProvider', 'HuggingFaceVisionProvider'):
        cls = getattr(providers, name)
        instance = cls.__new__(cls)
        response = instance.generate('prompt', b'fixture')
        assert response['ok'] is False
        assert response['reason'] == 'vision_pricing_not_verified'


def test_direct_text_transports_cannot_bypass_ledger(managed, monkeypatch):
    import httpx
    import providers
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert providers.openai_text_generate('prompt')['deferred']
    assert providers.claude_text_generate('prompt')['deferred']


def test_ai_suggestion_has_no_unmetered_fallback(managed, monkeypatch):
    import httpx
    import ai
    monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON')
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert ai.suggest_fix('2.4.4', 'Link purpose', 'A', 'fixture.docx', detail='vague') is None
    assert managed.deferred[-1]['reason'] == 'verified_model_pricing_unavailable'


def test_ai_direct_paths_defer_before_threads_or_transport(managed, monkeypatch):
    import httpx
    import ai
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert ai._vision_generate('prompt', b'fixture') is None
    assert ai._bounded_vision_generate(None, 'prompt', b'fixture')['ok'] is False
    assert ai.copilot_guidance(b'fixture') is None
    assert ai.describe_reading_order(b'fixture') is None
    assert ai.simplify_text('fixture') is None
    assert ai._ollama_narrative({}) is None
    assert ai.suggest_fix('1.1.1', 'Alt text', 'A', 'x', image_bytes=b'fixture') is None


def test_cached_usage_requires_explicit_price_support(specs):
    data = result(usage={'prompt_tokens': 100, 'completion_tokens': 10,
        'prompt_tokens_details': {'cached_tokens': 50}})
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: Response(data))
    with pytest.raises(ValueError, match='cached'):
        generator.generate_text(specs[0].model, 'prompt')


def test_anthropic_measured_transport(specs, monkeypatch):
    monkeypatch.setattr(FakeProviders, 'selected', 'anthropic')
    specs = tuple(replace(s, provider='anthropic') for s in specs)
    calls = []
    data = {'model': specs[0].model, 'id': 'fixture',
        'usage': {'input_tokens': 100, 'output_tokens': 10},
        'content': [{'type': 'text', 'text': 'Useful draft'}]}
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: calls.append(kw) or Response(data))
    draft = generator.generate_text(specs[0].model, 'prompt')
    assert draft['text'] == 'Useful draft'
    assert draft['cost_usd'] == '0.00012'
    assert calls[0]['json']['max_tokens'] == 128


def test_successful_ai_suggestion_keeps_human_approval(managed, monkeypatch):
    import httpx
    import ai
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: Response(result(text='Annual report')))
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: 'fixture-trace')
    draft = ai.suggest_fix('2.4.4', 'Link purpose', 'A', 'fixture.docx')
    assert draft['suggestion'] == 'Annual report'
    assert draft['approval_required'] is True
    assert draft['attempts'][0]['cost_usd'] == '0.00012'


def test_explanation_does_not_bypass_managed_run(managed, monkeypatch):
    import httpx
    import ai
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert ai.explain_finding('x', 'x', 'A', 'x', 1, 'x', []) is None


def test_managed_text_availability_does_not_require_ollama(managed, monkeypatch):
    import ai
    monkeypatch.setattr(ai, '_tags_cached', lambda: pytest.fail('legacy probe'))
    assert ai.model_is_available() is True
    assert ai.vision_is_available() is False
    assert 'spending bound' in ai.vision_unavailable_reason()


def test_verified_facade_binds_durable_context(managed, monkeypatch, specs):
    import ai
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: Response(result()))
    req = Request('op', '<html>Hi</html>', 'html-root-language', 'hitl', True, 'en', 'metadata:1')
    snapshots = []
    state = ai.run_verified_remediation(req, persist=snapshots.append, generator=generator)
    assert state['status'] == 'awaiting_approval'
    assert snapshots[-1]['candidate'] == '<html lang="en">Hi</html>'
    with pytest.raises(ValueError, match='identity'):
        ai.run_verified_remediation(req, persist=snapshots.append, generator=generator, owner_id='other')
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 120


def test_verified_facade_rejects_subjective_family_before_request(managed, specs):
    import ai
    req = Request('op', 'Hi', 'alt-text', 'auto', True)
    with pytest.raises(ValueError, match='verifier'):
        ai.run_verified_remediation(req, persist=lambda s: None, model_specs=specs)
    assert managed.ledger.snapshot('owner', 'run')['held_units'] == 0


@pytest.mark.parametrize('failure', ['oversized', 'key_removed', 'expired'])
def test_predispatch_rejection_releases_hold_and_allows_next_draft(managed, monkeypatch, specs, failure):
    import httpx
    import providers
    calls = []
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: calls.append(1) or Response(result(text='Draft')))
    generator = StrictTextGenerator(specs, provider_module=providers)
    monkeypatch.setattr(bounded, 'configured_generator', lambda: generator)
    prompt = 'x' * 9000 if failure == 'oversized' else 'prompt'
    if failure == 'key_removed':
        monkeypatch.setattr(providers, '_text_key_for', lambda provider: '')
    elif failure == 'expired':
        generator.clock = lambda: specs[0].verified_until + 1
    draft = providers.text_generate(prompt)
    assert draft['reason'] == 'request_rejected_before_dispatch'
    assert calls == []
    snapshot = managed.ledger.snapshot('owner', 'run')
    assert snapshot['held_units'] == 0
    assert snapshot['spent_units'] == 0
    assert not snapshot['blocked']
    monkeypatch.setattr(providers, '_text_key_for', FakeProviders._text_key_for)
    generator.clock = time.time
    assert providers.text_generate('prompt')['text'] == 'Draft'
    assert calls == [1]


def test_retry_does_not_purchase_same_draft_twice(managed, monkeypatch):
    import httpx
    import providers
    calls = []
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: calls.append(1) or Response(result(text='Draft')))
    assert providers.text_generate('same durable work')['text'] == 'Draft'
    again = providers.text_generate('same durable work')
    assert again['reason'] == 'existing_draft_attempt_requires_reconciliation'
    assert calls == [1]
    assert managed.ledger.snapshot('owner', 'run')['spent_units'] == 120
