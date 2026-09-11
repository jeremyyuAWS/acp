from types import MappingProxyType

import pytest
from ai_run_policy import RunContext, normalize_run_policy
from remediation_impact_settings import normalize_policy


def test_local_zone_survives_plan_normalization_and_denies_cloud_even_with_budget():
    selected = normalize_policy(dict(rule_based=2, ai=1, ai_zone='local', ai_budget_usd='20.00', ai_review={'enabled': False}))
    assert selected['ai_zone'] == 'local'
    ctx = RunContext(None, 'owner', 'scan', 'run', MappingProxyType(normalize_run_policy(selected)))
    assert ctx.local_drafting
    assert not ctx.enabled


@pytest.mark.parametrize('extra', [dict(ai_review={'enabled': True}), dict(generation_chain={'steps': []})])
def test_local_plan_rejects_cloud_review_or_chain(extra):
    with pytest.raises(ValueError, match='Local-only'):
        normalize_policy(dict(rule_based=2, ai=1, ai_zone='local', ai_budget_usd='0.00', **extra))


def test_cloud_policy_still_has_normal_budget_gate():
    ctx = RunContext(None, 'owner', 'scan', 'run', MappingProxyType(normalize_run_policy(dict(ai=1, ai_zone='any', ai_budget_usd='20.00'))))
    assert ctx.enabled
    assert not ctx.local_drafting


@pytest.mark.parametrize('review', [False, True, [], 'invalid'])
def test_local_review_malformed_shape_returns_validation_error(review):
    with pytest.raises(ValueError, match='Invalid AI review policy'):
        normalize_policy(dict(rule_based=2, ai=1, ai_zone='local', ai_budget_usd='0.00', ai_review=review))


def test_local_review_none_uses_existing_disabled_default():
    selected = normalize_policy(dict(rule_based=2, ai=1, ai_zone='local', ai_budget_usd='0.00', ai_review=None))
    assert selected['ai_review']['enabled'] is False
