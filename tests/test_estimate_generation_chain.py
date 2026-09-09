"""Synthetic contract fixtures only; never ingested as production evidence."""
from copy import deepcopy

from ai_review_calibration import config_id
from remediation_cohort_estimates import estimate_cohort
from test_remediation_cohort_estimates import cohort, APPLIES, NOW


def chain(size=2):
    return {'version': 1, 'steps': [dict(step_id=step_id, position=i,
        provider='anthropic', model=f'model-{i}', enabled=True, capabilities=['text'])
        for i, step_id in enumerate(('primary', 'fallback_1', 'fallback_2')[:size])]}


def configuration(selected=None):
    value = dict(format='html', change_family='link-label', generator_provider='anthropic',
                 generator_model='model-0', reviewer_provider='anthropic',
                 reviewer_model='reviewer', validator_version='validator-1')
    if selected is not None:
        value['generation_chain'] = selected
    return value


def test_configuration_digest_changes_when_third_generation_position_is_selected():
    assert config_id(configuration(chain(2))) != config_id(configuration(chain(3)))


def test_two_step_outcomes_and_costs_do_not_qualify_three_step_configuration():
    record = cohort()
    record['generation_chain'] = chain(2)
    # Even an incorrectly reused producer config_id cannot bypass the chain comparison.
    result = estimate_cohort(record, applicability={**APPLIES, 'generation_chain': chain(3)},
                             eligible_findings=100, now=NOW)
    assert not result['available']
    assert result['additional_usable_suggestions_range'] is None
    assert result['expected_provider_cost_range_usd'] is None


def test_legacy_ids_remain_byte_for_byte_compatible_but_never_alias_explicit_chain():
    import hashlib
    import json
    legacy = configuration()
    old = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    assert config_id(legacy) == old
    assert config_id(configuration(chain(2))) != old
    assert config_id(configuration(chain(3))) != old


def test_digest_binds_fallback_identity_order_provider_reviewer_and_validator():
    baseline = configuration(chain(3))
    changes = []
    other = deepcopy(baseline); other['generation_chain']['steps'][2]['model'] = 'different'; changes.append(other)
    other = deepcopy(baseline)
    other['generation_chain']['steps'][1]['model'], other['generation_chain']['steps'][2]['model'] = 'model-2', 'model-1'
    changes.append(other)
    other = deepcopy(baseline); other['generator_provider'] = 'openai'
    for step in other['generation_chain']['steps']:
        step['provider'] = 'openai'
    changes.append(other)
    for field in ('reviewer_model', 'reviewer_provider', 'validator_version'):
        other = deepcopy(baseline); other[field] = 'different'; changes.append(other)
    assert all(config_id(other) != config_id(baseline) for other in changes)


def test_ingestion_uses_shared_normalizer_and_does_not_requalify_old_version(isolated_store):
    import pytest
    from ai_review_calibration import ingest_evaluation, read_evaluation, applicable_evaluation
    from test_ai_review_calibration import cohort as evaluation_fixture, NOW as evaluation_now, RULE
    value = {**evaluation_fixture(), **configuration(chain(2))}
    value['generation_chain']['unused'] = 'discarded'
    stored = ingest_evaluation(isolated_store, 'owner', value)
    assert 'unused' not in stored['generation_chain']
    assert stored['config_id'] == config_id(configuration(chain(2)))
    result = applicable_evaluation(isolated_store, 'owner', value['evaluation_version'], configuration(chain(3)), RULE, now=evaluation_now)
    assert result['reason'] == 'calibration_configuration_mismatch'
    with pytest.raises(ValueError, match='immutable'):
        ingest_evaluation(isolated_store, 'owner', {**value, 'generation_chain': chain(3)})
    assert read_evaluation(isolated_store, 'owner', value['evaluation_version']) == stored


def test_legacy_cohort_does_not_qualify_any_explicit_chain():
    for size in (2, 3):
        result = estimate_cohort(cohort(), applicability={**APPLIES, 'generation_chain': chain(size)}, eligible_findings=100, now=NOW)
        assert result['reason'] == 'generation_chain_mismatch'
        assert result['expected_provider_cost_range_usd'] is None


def test_matching_three_step_cohort_can_produce_fixture_estimate():
    record = cohort(); record['generation_chain'] = chain(3)
    result = estimate_cohort(record, applicability={**APPLIES, 'generation_chain': chain(3)}, eligible_findings=100, now=NOW)
    assert result['available']
    assert result['additional_usable_suggestions_range'] == [59, 86]
    assert result['expected_provider_cost_range_usd'] == ['2.00', '2.00']


def test_policy_change_invalidates_old_context_before_any_registry_read():
    from remediation_cohort_estimates import read_plan_estimate
    from test_remediation_cohort_estimates import bound_preview
    preview = bound_preview()
    preview['policy'] = {'generation_chain': chain(3)}
    preview['estimate_context']['generation_chain'] = chain(2)
    preview['estimate_population']['generation_chain'] = chain(2)
    assert read_plan_estimate(object(), 'owner', preview)['reason'] == 'generation_chain_mismatch'
    preview['estimate_context']['generation_chain'] = chain(3)
    assert read_plan_estimate(object(), 'owner', preview)['reason'] == 'generation_chain_mismatch'


def test_population_chain_is_passed_through_even_if_producer_reuses_config_id():
    from remediation_cohort_estimates import estimate_plan
    from test_remediation_cohort_estimates import bound_preview
    population = bound_preview()['estimate_population']
    population['generation_chain'] = chain(3)
    record = cohort(); record['generation_chain'] = chain(2)
    result = estimate_plan([record], population, now=NOW)
    assert result['reason'] == 'generation_chain_mismatch'
    assert result['additional_usable_suggestions_range'] is None


def test_malformed_or_ambiguous_chain_cannot_qualify():
    import pytest
    invalid = [None, {'version': 2, 'steps': chain()['steps']}, {'version': True, 'steps': chain()['steps']}]
    reordered = chain(); reordered['steps'].reverse(); invalid.append(reordered)
    for selected in invalid:
        with pytest.raises(ValueError):
            config_id(configuration(selected) if selected is not None else {**configuration(), 'generation_chain': None})
        record = cohort(); record['generation_chain'] = selected
        assert not estimate_cohort(record, applicability={**APPLIES, 'generation_chain': selected}, eligible_findings=100, now=NOW)['available']
    value = configuration(chain()); value['generator_model'] = 'different-primary'
    with pytest.raises(ValueError, match='primary'):
        config_id(value)
