from copy import deepcopy
import pytest
from remediation_cohort_estimates import estimate_cohort, normalize_impact_evidence

NOW = '2026-09-08T00:00:00Z'
APPLIES = dict(format='html', change_family='link-label', config_id='exact-config-1')


def cohort(n=40):
    return dict(**APPLIES, evaluation_version='v1', evaluated_at='2026-09-07T00:00:00Z',
                provenance=dict(kind='evaluated', qualification_owner='owner', representative=True, production_approved=True, approval_ref='fixture-only-not-production', dataset_sha256='a'*64, evaluation_report_sha256='b'*64),
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


def test_plan_scope_is_deduplicated_and_mixed_config_is_unavailable():
    from remediation_cohort_estimates import estimate_plan
    row = dict(**APPLIES, finding_id='f', source_revision='s', eligible=True)
    population = dict(complete=True, scope_revision='scope-2', assessment_revision='a1', configuration_revision=APPLIES['config_id'], findings=[row, deepcopy(row)])
    result = estimate_plan([cohort()], population, now=NOW)
    assert result['eligible_findings'] == 1 and result['scope_revision'] == 'scope-2'
    population['findings'][1]['config_id'] = 'other'
    assert estimate_plan([cohort()], population, now=NOW)['reason'] == 'out_of_population'
    population['complete'] = False
    assert not estimate_plan([cohort()], population, now=NOW)['available']


def test_current_routing_groups_do_not_invent_a_population():
    from remediation_cohort_estimates import read_plan_estimate
    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError('No provider or storage call needed without targeting')
    assert not read_plan_estimate(NoCalls(), 'owner', {'findings': [{'finding_count': 100}]})['available']


def test_source_revisions_are_not_independent_finding_samples():
    r = cohort()
    duplicate = deepcopy(r['impact_evidence']['samples'][0])
    duplicate['source_revision'] = 's2'
    r['impact_evidence']['samples'].append(duplicate)
    r['impact_evidence']['population_size'] += 1
    assert estimate(r)['reason'] == 'missing_or_conflicting_lineage'


def test_registry_failure_preserves_routing_and_hides_private_exception(monkeypatch):
    import sys
    from types import SimpleNamespace
    from remediation_cohort_estimates import read_plan_estimate
    def broken(*args):
        raise RuntimeError('private record contents')
    monkeypatch.setitem(sys.modules, 'ai_review_calibration', SimpleNamespace(load_calibration_records=broken))
    result = read_plan_estimate(ContextStore(), 'owner', bound_preview())
    assert result['reason'] == 'evaluation_read_unavailable'
    assert 'private' not in str(result)


def test_shared_registry_reader_is_owner_scoped(monkeypatch):
    import sys
    from types import SimpleNamespace
    from remediation_cohort_estimates import read_plan_estimate
    seen = []
    def read(store, owner):
        seen.append(owner)
        return []
    monkeypatch.setitem(sys.modules, 'ai_review_calibration', SimpleNamespace(load_calibration_records=read))
    row = dict(**APPLIES, finding_id='f', source_revision='s', eligible=True)
    result = read_plan_estimate(ContextStore(), 'alice', bound_preview())
    assert seen == ['alice']
    assert not result['available'] and result['assessment_revision'] == 'a1'


@pytest.mark.parametrize('policy', [{'ai': 0}, {'ai': 1, 'ai_budget_usd': '0.00'}])
def test_rules_only_or_zero_budget_does_not_offer_future_ai_estimates(policy):
    from remediation_cohort_estimates import read_plan_estimate
    assert read_plan_estimate(object(), 'owner', {'policy': policy})['reason'] == 'ai_not_planned'


def test_zero_usable_outcomes_has_no_cost_per_usable_denominator():
    r = cohort()
    for sample in r['impact_evidence']['samples']:
        sample['usable'] = False
    result = estimate(r)
    assert result['available']
    assert result['additional_usable_suggestions_range'][0] == 0
    assert result['observed_cost_per_usable_outcome_usd'] is None
    assert result['expected_provider_cost_range_usd'] == ['2.00', '2.00']


@pytest.mark.parametrize('missing', ['scope_revision', 'assessment_revision', 'configuration_revision'])
def test_unversioned_producer_cannot_enable_numeric_estimates(missing):
    from remediation_cohort_estimates import estimate_plan
    population = dict(complete=True, scope_revision='s1', assessment_revision='a1', configuration_revision=APPLIES['config_id'],
                      findings=[dict(**APPLIES, finding_id='f', source_revision='v', eligible=True)])
    population.pop(missing)
    assert not estimate_plan([cohort()], population, now=NOW)['available']


class ContextStore:
    def get_scan(self, scan_id, owner=None):
        return {'id': scan_id}
    def current_stage_output_manifest(self, scan_id, stage):
        return {'manifest_id': 'a1'}


def bound_preview():
    from remediation_cohort_estimates import estimate_scope_revision
    context = dict(assessment_revision='a1', configuration_revision=APPLIES['config_id'],
                   scope_revision=estimate_scope_revision('a1', ['selected.html']))
    return dict(scan_id='s', files=[{'file': 'selected.html'}], estimate_context=context,
                estimate_population=dict(**context, complete=True,
                    findings=[dict(**APPLIES, finding_id='f', source_revision='v1', eligible=True)]))


def test_reader_rejects_missing_current_config_and_changed_manifest():
    from remediation_cohort_estimates import read_plan_estimate
    preview = bound_preview()
    preview.pop('estimate_context')
    assert read_plan_estimate(ContextStore(), 'owner', preview)['reason'] == 'current_estimate_context_unavailable'
    preview = bound_preview()
    preview['files'] = [{'file': 'other.html'}]
    assert read_plan_estimate(ContextStore(), 'owner', preview)['reason'] == 'stale_assessment_or_scope'
    class NewAssessment(ContextStore):
        def current_stage_output_manifest(self, *args):
            return {'manifest_id': 'a2'}
    assert read_plan_estimate(NewAssessment(), 'owner', bound_preview())['reason'] == 'stale_assessment_or_scope'


@pytest.mark.parametrize('field', ['representative', 'production_approved', 'approval_ref'])
def test_hashes_alone_do_not_qualify_production_evidence(field):
    r = cohort(); r['provenance'].pop(field)
    assert not estimate(r)['available']



def test_foreign_qualification_record_cannot_supply_owner_estimate(monkeypatch):
    import sys
    from types import SimpleNamespace
    import remediation_cohort_estimates as module
    record = cohort()
    record['provenance']['qualification_owner'] = 'another-owner'
    monkeypatch.setitem(sys.modules, 'ai_review_calibration', SimpleNamespace(load_calibration_records=lambda *args: [record]))
    original = module.estimate_plan
    seen = []
    def observe(records, population, **kwargs):
        seen.extend(records)
        return original(records, population, now=NOW)
    monkeypatch.setattr(module, 'estimate_plan', observe)
    result = module.read_plan_estimate(ContextStore(), 'owner', bound_preview())
    assert seen == []
    assert not result['available']


def test_current_manifest_with_different_configuration_is_unavailable():
    from remediation_cohort_estimates import read_plan_estimate
    preview = bound_preview()
    preview['estimate_context']['configuration_revision'] = 'new-current-model'
    assert read_plan_estimate(ContextStore(), 'owner', preview)['reason'] == 'current_estimate_context_unavailable'
