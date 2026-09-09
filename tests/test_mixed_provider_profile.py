"""Catalog shape for every bounded text profile, including the mixed-provider chain.

No provider is activated and no HTTP is performed here: these assert the shape and
the provenance of the static catalog, plus the one governance rule that decides
whether a mixed chain can actually dispatch.
"""
import pytest

from ai_model_profiles import PROFILES, SECOND_FALLBACK, VERIFIED_UNTIL, model_config
from llm_waterfall_provider import StrictTextGenerator, TextModelSpec
from test_llm_waterfall_provider import FakeProviders

ALL_PROFILES = sorted(PROFILES)


@pytest.mark.parametrize('profile', ALL_PROFILES)
def test_every_profile_yields_exactly_two_without_second_fallback(profile):
    assert len(model_config(profile)) == 2


@pytest.mark.parametrize('profile', ALL_PROFILES)
def test_second_fallback_adds_a_third_step_only_where_registered(profile):
    base = model_config(profile)
    selected = model_config(profile, include_second_fallback=True)
    # configured_generator() rejects anything that is not 2 or 3 items.
    assert len(selected) in (2, 3)
    assert selected[:2] == base
    assert len(selected) == (3 if profile in SECOND_FALLBACK else 2)


def test_openai_balanced_has_no_third_step_from_verified_specs():
    # Both verified OpenAI specs are already the two steps of this chain; a third
    # would duplicate a model ID or invent a spec. Recorded, not silently absent.
    assert 'openai-balanced' not in SECOND_FALLBACK
    assert len(model_config('openai-balanced', include_second_fallback=True)) == 2


@pytest.mark.parametrize('profile', ALL_PROFILES)
def test_every_spec_constructs_a_valid_text_model_spec(profile):
    specs = [TextModelSpec(**item) for item in
             model_config(profile, include_second_fallback=True)]
    for spec in specs:
        spec.validate(0)
        assert spec.verified_until == VERIFIED_UNTIL
    # StrictTextGenerator requires distinct model IDs across the chain.
    assert len({spec.model for spec in specs}) == len(specs)


@pytest.mark.parametrize('profile', ALL_PROFILES)
def test_chain_escalates_cheapest_first_by_reserved_maximum(profile):
    from decimal import Decimal
    reserved = [Decimal(TextModelSpec(**item).maximum_cost()) for item in
                model_config(profile, include_second_fallback=True)]
    assert reserved == sorted(reserved) and len(set(reserved)) == len(reserved)


def test_mixed_profile_spans_two_distinct_providers():
    two = model_config('mixed-balanced')
    three = model_config('mixed-balanced', include_second_fallback=True)
    assert {item['provider'] for item in two} == {'anthropic', 'openai'}
    assert {item['provider'] for item in three} == {'anthropic', 'openai'}
    assert [item['model'] for item in three] == [
        'claude-haiku-4-5-20251001', 'gpt-4.1-mini-2025-04-14', 'claude-sonnet-5']


def test_mixed_profile_reuses_already_verified_specs_verbatim():
    # Copying a verified spec is not a new pricing claim; this is what makes that true.
    mixed = model_config('mixed-balanced', include_second_fallback=True)
    assert mixed[0] == model_config('anthropic-balanced')[0]
    assert mixed[1] == model_config('openai-balanced')[0]
    assert mixed[2] == model_config('anthropic-balanced')[1]


@pytest.mark.parametrize('profile', ALL_PROFILES)
def test_returned_config_is_a_deep_copy_callers_cannot_mutate(profile):
    first = model_config(profile, include_second_fallback=True)
    untouched = model_config(profile, include_second_fallback=True)
    first[0]['input_usd_per_million'] = '999999.00'
    first[0]['model'] = 'mutated'
    first.append(first[0])
    del first[1]
    assert model_config(profile, include_second_fallback=True) == untouched
    assert model_config(profile) == untouched[:2]
    assert PROFILES[profile][0]['model'] != 'mutated'
    if profile in SECOND_FALLBACK:
        assert SECOND_FALLBACK[profile]['input_usd_per_million'] != '999999.00'


@pytest.mark.parametrize('active', ['anthropic', 'openai'])
def test_mixed_chain_is_refused_by_single_provider_governance(active):
    """The transport, not the catalog, is what blocks a mixed chain today.

    StrictTextGenerator requires every spec to match the owner-selected provider,
    so 'mixed-balanced' cannot dispatch under either selection until that rule is
    widened in llm_waterfall_provider.py. Asserted rather than assumed.
    """
    class Selected(FakeProviders):
        selected = active

    specs = tuple(TextModelSpec(**item) for item in
                  model_config('mixed-balanced', include_second_fallback=True))
    with pytest.raises(ValueError, match='owner-selected text provider'):
        StrictTextGenerator(specs, provider_module=Selected,
                            post=lambda *a, **kw: pytest.fail('unexpected request'))


@pytest.mark.parametrize('profile,provider', [('openai-balanced', 'openai'),
                                              ('anthropic-balanced', 'anthropic')])
def test_single_provider_profiles_still_construct_a_generator(profile, provider):
    class Selected(FakeProviders):
        selected = provider

    generator = StrictTextGenerator(
        tuple(TextModelSpec(**item) for item in
              model_config(profile, include_second_fallback=True)),
        provider_module=Selected, post=lambda *a, **kw: pytest.fail('unexpected request'))
    assert [model.name for model in generator.models] == [
        item['model'] for item in model_config(profile, include_second_fallback=True)]
