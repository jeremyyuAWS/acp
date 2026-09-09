import hashlib
import json
from types import SimpleNamespace
import pytest

from ai_review_chain import review_managed_draft
from ai_review_policy import approval_gate, normalize_review_policy
from remediation_impact_settings import normalize_policy
from ai_run_policy import normalize_run_policy


def context(**policy):
    return SimpleNamespace(policy={'ai_review': {'enabled': True, **policy}})


GENERATOR = SimpleNamespace(models=[SimpleNamespace(name='first'), SimpleNamespace(name='second')])
DRAFT = {'text': 'Actual drafted content', 'model': 'first', 'provider': 'anthropic'}


def test_optional_review_uses_other_model_and_does_not_rewrite_or_autoapprove():
    calls = []
    def generate(prompt, ctx, generator, **kwargs):
        calls.append((prompt, kwargs))
        return {'text': json.dumps({'verdict': 'accept', 'reason': 'The wording matches the source.'}),
                'model': 'second', 'provider': 'anthropic', 'cost_usd': '.001'}
    result = review_managed_draft('Task with source', DRAFT, context(), GENERATOR, generate=generate)
    assert result['text'] == DRAFT['text']
    assert result['model'] == 'first'
    assert result['approval_required'] is True
    assert result['review']['verdict'] == 'accept'
    assert calls[0][1] == {'purpose': 'review', 'tier_indices': (2,)}
    assert 'untrusted data' in calls[0][0]


def test_low_cost_review_policy_uses_the_first_configured_model():
    calls = []
    def generate(prompt, ctx, generator, **kwargs):
        calls.append(kwargs)
        return {'text': json.dumps({'verdict': 'accept', 'reason': 'The wording is usable.'}),
                'model': 'first', 'provider': 'anthropic', 'cost_usd': '.0001'}
    result = review_managed_draft(
        'Task with source', DRAFT, context(review_model='low_cost'), GENERATOR, generate=generate)
    assert result['review']['verdict'] == 'accept'
    assert calls[0] == {'purpose': 'review', 'tier_indices': (1,)}


def test_final_review_is_bounded_and_disagreement_stays_for_person():
    calls = []
    def generate(prompt, ctx, generator, **kwargs):
        calls.append(kwargs)
        return {'text': '{"verdict":"revise","reason":"Missing source evidence."}'}
    result = review_managed_draft('Task', DRAFT, context(max_review_attempts=2, mode='threshold'), GENERATOR, generate=generate)
    assert [call['purpose'] for call in calls] == ['review', 'final_review']
    assert result['review']['verdict'] == 'revise'
    assert result['approval_required'] is True


@pytest.mark.parametrize('reason', ['provider_refused', 'budget_admission_denied', 'provider_usage_unknown'])
def test_refusal_budget_or_uncertainty_does_not_escalate(reason):
    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        return {'deferred': True, 'reason': reason}
    result = review_managed_draft('Task', DRAFT, context(max_review_attempts=2), GENERATOR, generate=generate)
    assert len(calls) == 1
    assert result['review']['verdict'] == 'unable'
    assert result['text'] == DRAFT['text']


def test_disabled_review_makes_no_call():
    result = review_managed_draft('Task', DRAFT, context(enabled=False), GENERATOR,
                                 generate=lambda *a, **k: pytest.fail('unexpected call'))
    assert result is DRAFT


@pytest.mark.parametrize('lower,requires', [(.94999, True), (.95, True), (.96, True)])
def test_generic_scalar_estimates_never_authorize_structured_proposals(lower, requires):
    digest = hashlib.sha256(b'proposal').hexdigest()
    args = dict(review={'verdict':'accept','proposal_sha256':digest}, estimate={'available':True,'reliability_lower_bound':lower},
                validation={'passed':True,'proposal_sha256':digest,'source_revision':'r1'}, proposal_sha256=digest, source_revision='r1', supported=True)
    policy = {'enabled':True,'mode':'threshold','minimum_reliability':95}
    assert approval_gate(policy, **args)['approval_required'] is requires
    for changed in ({'supported':False}, {'estimate':None}, {'source_revision':'r2'}, {'review':{'verdict':'revise'}}):
        assert approval_gate(policy, **{**args, **changed})['approval_required'] is True


def test_review_preferences_are_preserved_in_the_immutable_run_snapshot():
    value = {'rule_based':2,'ai':1,'ai_budget_usd':'5','ai_review':{'enabled':True,'mode':'threshold','minimum_reliability':98}}
    normalized = normalize_policy(value)
    assert normalize_run_policy(normalized)['ai_review'] == normalize_review_policy(value['ai_review'])
    assert normalize_run_policy({'ai':1,'ai_budget_usd':'5.00'}).get('ai_review') is None


@pytest.mark.parametrize('policy', [{'minimum_reliability':-1}, {'minimum_reliability':True},
    {'minimum_reliability':101}, {'max_review_attempts':3}, {'enabled':'true'}, {'mode':'threshold'}, {'model_confidence':100}])
def test_invalid_or_unbounded_review_preferences_rejected(policy):
    with pytest.raises(ValueError):
        normalize_review_policy(policy)
