from copy import deepcopy
import pytest
from remediation_cohort_estimates import estimate_cohort, normalize_impact_evidence

NOW = '2026-09-08T00:00:00Z'
APPLIES = dict(format='html', change_family='link-label', config_id='exact-config-1')


def cohort(n=40):
    return dict(**APPLIES, evaluation_version='v1', evaluated_at='2026-09-07T00:00:00Z',
                provenance=dict(kind='evaluated', dataset_sha256='a'*64, evaluation_report_sha256='b'*64),
                impact_evidence=dict(schema_version='ai-impact-cohort.v1', representative=True,
                    population_size=n, expires_at='2026-09-20T00:00:00Z', charges_complete=True,
                    samples=[dict(finding_id=str(i), source_revision='s1', operation_id=str(i), evidence_id='label-'+str(i),
                        observed_at='2026-09-06T00:00:00Z', rules_unresolved=True, usable=i < 30) for i in range(n)],
                    charges=[dict(charge_id=str(i), operation_id=str(i), purpose='generation', status='settled', amount_usd='0.02') for i in range(n)]))


def estimate(record, **kwargs):
    return estimate_cohort(record, applicability=APPLIES, eligible_findings=100, now=NOW, **kwargs)


def test_representative_range_and_cost_denominator_include_failed_outcomes():
    result = estimate(cohort())
    assert result['available']
    assert result['additional_usable_suggestions_range'] == [59, 86]
    assert result['expected_provider_cost_range_usd'] == ['2.00', '2.00']
    assert float(result['observed_cost_per_usable_outcome_usd']) == pytest.approx(.8/30)
    assert result['sample_size'] == 40


@pytest.mark.parametrize('mutation,reason', [
    (lambda r: r.update(format='pdf'), 'out_of_population'),
    (lambda r: r.update(config_id='other-reviewer'), 'out_of_population'),
    (lambda r: r['provenance'].update(kind='synthetic'), 'representative_evidence_unavailable'),
    (lambda r: r['impact_evidence'].update(representative=False), 'representative_evidence_unavailable'),
    (lambda r: r['impact_evidence'].update(expires_at=NOW), 'stale_evidence'),
    (lambda r: r['impact_evidence']['samples'][0].pop('source_revision'), 'missing_or_conflicting_lineage'),
    (lambda r: r['impact_evidence']['samples'][0].update(rules_unresolved=False), 'missing_or_conflicting_lineage'),
])
def test_inapplicable_evidence_never_produces_numbers(mutation, reason):
    r = cohort(); mutation(r)
    result = estimate(r)
    assert not result['available'] and result['reason'] == reason
    assert result['additional_usable_suggestions_range'] is None


def test_sparse():
    assert estimate(cohort(10))['reason'] == 'insufficient_samples'


def test_dedup_retries_and_revision_replays():
    r = cohort(); e = r['impact_evidence']
    e['samples'] += deepcopy(e['samples'])
    e['charges'] += deepcopy(e['charges'])
    assert estimate(r) == estimate(cohort())
    e['samples'][-1]['usable'] = True
    assert estimate(r)['reason'] == 'missing_or_conflicting_lineage'


@pytest.mark.parametrize('status', ['held', 'unknown'])
def test_unsettled_charge_is_separate_and_blocks_cost_only(status):
    r = cohort(); r['impact_evidence']['charges'][0]['status'] = status
    result = estimate(r)
    assert result['available']
    assert result['expected_provider_cost_range_usd'] is None
    assert result['cohort_spending']['generation_usd'] == '0.78'
    assert result['cohort_spending']['unknown_charges'] == (status == 'unknown')


def test_review_charge_separate_including_retries():
    r = cohort()
    r['impact_evidence']['charges'] += [dict(charge_id='review', operation_id='0', purpose='review', status='settled', amount_usd='0.1')]
    result = estimate(r)
    assert result['cohort_spending']['review_usd'] == '0.1'
    assert result['expected_provider_cost_range_usd'] == ['2.00', '12.00']


def test_missing_invoice_and_incomplete_ledger_are_not_free():
    r = cohort(); r['impact_evidence']['charges'].pop()
    assert estimate(r)['expected_provider_cost_range_usd'] is None
    r = cohort(); r['impact_evidence']['charges_complete'] = False
    assert estimate(r)['expected_provider_cost_range_usd'] is None


def test_content_is_not_ingested_or_returned():
    r = cohort(); r['impact_evidence']['samples'][0]['prompt'] = 'secret document content'
    assert 'secret document content' not in str(normalize_impact_evidence(r['impact_evidence']))
    assert 'finding_id' not in str(estimate(r))
    assert 'secret document content' not in str(estimate(r))
