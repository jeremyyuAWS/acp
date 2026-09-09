"""Verified catalog configuration does not assert credential access or make probes."""
from dataclasses import replace
import pytest
from ai_model_profiles import model_config
from llm_waterfall_provider import StrictTextGenerator, TextModelSpec, ProviderAccessDenied
from test_llm_waterfall_provider import FakeProviders, Response


class AnthropicProviders(FakeProviders):
    selected = 'anthropic'


def test_optional_catalog_preserves_default_two_and_bounded_text_request():
    legacy = model_config('anthropic-balanced')
    selected = model_config('anthropic-balanced',include_second_fallback=True)
    assert len(legacy)==2 and selected[:2]==legacy and len(selected)==3
    assert selected[2]['model']=='claude-opus-5'
    calls=[]
    def post(*args,**kw):
        calls.append(kw)
        return Response(dict(model='claude-opus-5',id='fixture',usage=dict(input_tokens=100,output_tokens=10),
                             content=[dict(type='text',text='Quarterly Revenue Growth Overview')],stop_reason='end_turn'))
    generator=StrictTextGenerator(tuple(TextModelSpec(**s) for s in selected),provider_module=AnthropicProviders,post=post)
    output=generator.generate_text('claude-opus-5','fixture')
    assert output['cost_usd']=='0.00075'
    assert calls[0]['json']['thinking']=={'type':'disabled'}
    assert calls[0]['json']['output_config']=={'effort':'high'}
    assert calls[0]['json']['max_tokens']==1024
    assert 'fallbacks' not in calls[0]['json']
    assert generator.models[2].max_cost_usd=='5.0256'


@pytest.mark.parametrize('code',[401,403])
def test_candidate_access_denial_is_explicit_without_second_request(code):
    specs=tuple(TextModelSpec(**s) for s in model_config('anthropic-balanced',include_second_fallback=True))
    calls=[]
    response=Response({})
    response.status_code=code
    generator=StrictTextGenerator(specs,provider_module=AnthropicProviders,post=lambda *a,**kw:calls.append(kw) or response)
    with pytest.raises(ProviderAccessDenied):
        generator.generate_text('claude-opus-5','fixture')
    assert len(calls)==1


def test_plain_text_mode_is_not_general_provider_override():
    spec=TextModelSpec(**model_config('anthropic-balanced',include_second_fallback=True)[2])
    with pytest.raises(ValueError,match='plain-text'):
        replace(spec,model='unverified-model').validate(0)
