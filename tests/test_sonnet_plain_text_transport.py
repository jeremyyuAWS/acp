"""Sonnet 5 adaptive thinking must be disabled for the bounded text-only adapter."""
import time
import pytest
from llm_waterfall_provider import StrictTextGenerator, TextModelSpec
from test_llm_waterfall_provider import FakeProviders, Response

@pytest.mark.parametrize('model,disabled', [('claude-sonnet-5', True), ('fixture-legacy-model', False)])
def test_text_only_request_is_explicit_for_sonnet_five(model, disabled):
    class Anthropic(FakeProviders):
        selected = 'anthropic'
    specs = tuple(TextModelSpec('anthropic', name, 'fixture-price-v1', '1', '2',
        8192, 128, int(time.time()) + 3600) for name in (model, 'fixture-fallback'))
    calls = []
    def post(*a, **kw):
        calls.append(kw)
        assert (kw['json'].get('thinking') == {'type': 'disabled'}) is disabled
        return Response({'id': 'fixture-call', 'model': model,
            'usage': {'input_tokens': 100, 'output_tokens': 10},
            'content': [{'type': 'text', 'text': 'A visible diagram.'}]})
    generated = StrictTextGenerator(specs, provider_module=Anthropic, post=post).generate_text(model, 'prompt')
    assert generated['text'] == 'A visible diagram.'
    assert generated['cost_usd'] == '0.00012'
    assert len(calls) == 1 and calls[0]['json']['max_tokens'] == 128
