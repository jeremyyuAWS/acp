from copy import deepcopy
from datetime import datetime, timezone
import pytest
from remediation_impact_estimates import build_impact_estimate, wilson_interval

NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)

def cohort(size=100, successes=95):
    evaluation = dict(version='evaluation-7', config_id='generator-reviewer-revision-4',
                      change_family='link-label', validated=True, population_complete=True,
                      population_size=size, evaluated_at='2026-09-07T00:00:00Z',
                      expires_at='2026-10-01T00:00:00Z')
    samples = [dict(sample_id=f'case-{i}', config_id=evaluation['config_id'],
                    change_family=evaluation['change_family'], evaluation_version=evaluation['version'],
                    outcome='success' if i < successes else 'failure', evidence_id=f'evidence-{i}',
                    proposal_version='v1', source_revision=f'source-{i}',
                    observed_at='2026-09-06T00:00:00Z', cost_usd='0.002' if i % 2 else '0.005',
                    cost_settled=True, cost_attribution='sample') for i in range(size)]
    return evaluation, samples

def estimate(evaluation, samples, **kwargs):
    return build_impact_estimate(samples, evaluation=evaluation,
        config_id='generator-reviewer-revision-4', change_family='link-label', now=NOW, **kwargs)

def test_measured_complete_cohort_has_interval_and_observed_cost_range():
    evaluation, samples = cohort()
    result = estimate(evaluation, samples)
    assert result['available']
    assert result['sample_size'] == 100
    assert result['reliability_lower_bound'] == pytest.approx(0.8882495308)
    assert result['reliability_range'][1] == pytest.approx(0.9784563208)
    assert result['cost_range_usd'] == ['0.002', '0.005']
    assert result['cost_range_kind'] == 'observed_sample_min_max'
    assert result['evaluation_version'] == 'evaluation-7'

def test_missing_calibration_does_not_treat_generation_as_success():
    _, samples = cohort()
    result = estimate(None, samples)
    assert result['available'] is False
    assert result['reason'] == 'calibration_unavailable'
    assert result['reliability_lower_bound'] is None

@pytest.mark.parametrize('field,value,reason', [
    ('validated', False, 'calibration_not_validated'),
    ('version', '', 'calibration_not_validated'),
    ('config_id', 'different-reviewer', 'unsupported_cohort'),
    ('change_family', 'alt-text', 'unsupported_cohort'),
    ('population_complete', False, 'incomplete_evaluation_population'),
    ('population_size', 99, 'incomplete_evaluation_population'),
    ('expires_at', '2026-09-08T00:00:00Z', 'calibration_expired'),
    ('evaluated_at', '2026-08-01T00:00:00Z', 'calibration_expired'),
    ('evaluated_at', '2026-09-09T00:00:00Z', 'invalid_evaluation_dates'),
    ('evaluated_at', '2026-09-07', 'invalid_evaluation_dates'),
])
def test_calibration_must_match_and_be_fresh(field, value, reason):
    evaluation, samples = cohort(); evaluation[field] = value
    result = estimate(evaluation, samples)
    assert not result['available']
    assert result['reason'] == reason
    assert result['reliability_range'] is None

@pytest.mark.parametrize('field,value', [('evidence_id', ''), ('proposal_version', None),
    ('source_revision', ''), ('outcome', 'approved'), ('observed_at', '2026-09-08T01:00:00Z'),
    ('observed_at', '2026-07-08T00:00:00Z')])
def test_unknown_or_unlinked_samples_fail_closed(field, value):
    evaluation, samples = cohort(); samples[0][field] = value
    assert estimate(evaluation, samples)['reason'] == 'invalid_sample_evidence'

def test_minimum_size_is_enforced_and_cannot_be_relaxed_by_caller():
    evaluation, samples = cohort(29, 29)
    assert estimate(evaluation, samples)['reason'] == 'insufficient_samples'
    assert estimate(evaluation, samples, minimum_samples=1)['reason'] == 'invalid_evaluation_policy'
    evaluation, samples = cohort(30, 30)
    assert estimate(evaluation, samples)['available']
    assert estimate(evaluation, samples, minimum_samples=100)['reason'] == 'insufficient_samples'

def test_replayed_identical_cases_do_not_inflate_reliability():
    evaluation, samples = cohort()
    assert estimate(evaluation, samples + deepcopy(samples)) == estimate(evaluation, samples)
    changed = deepcopy(samples[0]); changed['outcome'] = 'failure'
    assert estimate(evaluation, samples + [changed])['reason'] == 'conflicting_sample_evidence'

def test_other_cohorts_are_excluded_without_silently_dropping_expected_cases():
    evaluation, samples = cohort()
    other = deepcopy(samples[0]); other.update(config_id='different', sample_id='other')
    assert estimate(evaluation, samples + [other])['sample_size'] == 100
    samples[0]['evaluation_version'] = 'old-version'
    assert estimate(evaluation, samples)['reason'] == 'incomplete_evaluation_population'

@pytest.mark.parametrize('field,value', [('cost_settled', False), ('cost_attribution', 'shared_call'),
    ('cost_usd', None), ('cost_usd', 'NaN'), ('cost_usd', '-0.01')])
def test_unknown_shared_or_unsettled_cost_is_not_zero_or_repeated(field, value):
    evaluation, samples = cohort(); samples[0][field] = value
    result = estimate(evaluation, samples)
    assert result['available']
    assert result['cost_range_usd'] is None
    assert result['cost_reason'] == 'attributed_cost_unavailable'

def test_wilson_extremes_do_not_promise_perfect_success():
    assert wilson_interval(100, 100)[0] < 1
    assert wilson_interval(0, 100)[1] > 0
    with pytest.raises(ValueError): wilson_interval(0, 0)
    with pytest.raises(ValueError): wilson_interval(True, 100)
