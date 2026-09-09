"""Read-only impact projection from the shared immutable calibration registry.

Independent labelled finding outcomes are the unit, never provider calls or revisions.
This projection grants no application permission and performs no provider requests.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import ceil, floor

from remediation_impact_estimates import _timestamp, wilson_interval

SCHEMA = 'ai-impact-cohort.v1'
DIMENSIONS = ('format', 'change_family', 'config_id')


def normalize_impact_evidence(value):
    """Validate ingestion; omit content-bearing fields and reject ambiguous replays."""
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
        raise ValueError('Invalid impact evidence schema')
    if type(value.get('representative')) is not bool or type(value.get('population_size')) is not int or value['population_size'] <= 0:
        raise ValueError('A declared evaluation population is required')
    expiry = _timestamp(value.get('expires_at'))
    if not expiry:
        raise ValueError('Impact evidence expiry must include timezone')
    rows = {}
    for sample in value.get('samples', []):
        keys = ('finding_id', 'source_revision', 'operation_id', 'evidence_id', 'observed_at')
        if not isinstance(sample, dict) or not all(isinstance(sample.get(k), str) and sample[k].strip() for k in keys):
            raise ValueError('Historical or missing finding lineage cannot support estimates')
        if not _timestamp(sample['observed_at']) or sample.get('rules_unresolved') is not True or type(sample.get('usable')) is not bool:
            raise ValueError('Independently labelled outcomes after rules are required')
        row = {k: sample[k] for k in keys}
        row.update(rules_unresolved=True, usable=sample['usable'])
        # One immutable source finding, regardless of retries, revisions or operations.
        identity = (row['finding_id'], row['source_revision'])
        if identity in rows and rows[identity] != row:
            raise ValueError('Conflicting finding outcome; ingest a canonical adjudicated label')
        rows[identity] = row
    if len(rows) != value['population_size']:
        raise ValueError('Incomplete evaluation population')
    charges = {}
    operations = {r['operation_id'] for r in rows.values()}
    for charge in value.get('charges', []):
        if not isinstance(charge, dict) or not isinstance(charge.get('charge_id'), str) or not charge['charge_id'] or charge.get('operation_id') not in operations:
            raise ValueError('Charge attribution is required')
        if charge.get('purpose') not in ('generation', 'review', 'adjudication') or charge.get('status') not in ('settled', 'held', 'unknown'):
            raise ValueError('Invalid charge state or purpose')
        amount = None
        if charge['status'] != 'unknown':
            try:
                amount = Decimal(str(charge.get('amount_usd')))
            except InvalidOperation as exc:
                raise ValueError('Invalid provider charge') from exc
            if not amount.is_finite() or amount < 0:
                raise ValueError('Invalid provider charge')
        row = {k: charge[k] for k in ('charge_id', 'operation_id', 'purpose', 'status')}
        row['amount_usd'] = str(amount) if amount is not None else None
        if row['charge_id'] in charges and charges[row['charge_id']] != row:
            raise ValueError('Conflicting charge replay')
        charges[row['charge_id']] = row
    return {'schema_version': SCHEMA, 'representative': value['representative'],
            'charges_complete': value.get('charges_complete') is True,
            'population_size': len(rows), 'expires_at': expiry.isoformat(),
            'samples': list(rows.values()), 'charges': list(charges.values())}


def estimate_cohort(record, *, applicability, eligible_findings, now=None):
    """95% interval for expected additional usable finding count, not a guarantee.

    Cost bounds conservatively scale observed cost per evaluated finding, including
    failed outcomes and retries. Cost per usable outcome is reported separately.
    """
    result = dict(schema_version=SCHEMA, available=False, reason='representative_evidence_unavailable',
                  sample_size=None, evaluation_version=None, applicability=dict(applicability),
                  additional_usable_suggestions_range=None, expected_provider_cost_range_usd=None,
                  cost_reason='complete_settled_charges_required')
    def fail(reason):
        return {**result, 'reason': reason}
    if not isinstance(record, dict):
        return result
    if any(not applicability.get(k) or record.get(k) != applicability[k] for k in DIMENSIONS):
        return fail('out_of_population')
    provenance = record.get('provenance') or {}
    if provenance.get('kind') != 'evaluated' or not all(provenance.get(k) for k in ('dataset_sha256', 'evaluation_report_sha256')):
        return result
    try:
        evidence = normalize_impact_evidence(record.get('impact_evidence'))
    except (ValueError, TypeError):
        return fail('missing_or_conflicting_lineage')
    if not evidence['representative']:
        return result
    current = _timestamp(now) if now is not None else datetime.now(timezone.utc)
    evaluated = _timestamp(record.get('evaluated_at'))
    expiry = _timestamp(evidence['expires_at'])
    if not current or not evaluated or evaluated > current or expiry <= evaluated:
        return fail('invalid_evaluation_dates')
    if current >= expiry or current - evaluated > timedelta(days=30):
        return fail('stale_evidence')
    rows = evidence['samples']
    if any(_timestamp(r['observed_at']) > evaluated or current - _timestamp(r['observed_at']) > timedelta(days=30) for r in rows):
        return fail('stale_or_invalid_samples')
    result.update(sample_size=len(rows), evaluation_version=record.get('evaluation_version'), evaluated_at=evaluated.isoformat(), expires_at=expiry.isoformat())
    if len(rows) < 30:
        return fail('insufficient_samples')
    if type(eligible_findings) is not int or not 1 <= eligible_findings <= 1000000:
        return fail('eligible_population_unknown')
    usable = sum(r['usable'] for r in rows)
    interval = wilson_interval(usable, len(rows))
    result.update(available=True, reason=None, eligible_findings=eligible_findings,
                  additional_usable_suggestions_range=[floor(interval[0] * eligible_findings), ceil(interval[1] * eligible_findings)],
                  uncertainty='95% Wilson interval for the expected count; individual runs can fall outside it.',
                  range_kind='expected_count_interval', confidence_level=0.95)
    charges = evidence['charges']
    totals = {p: sum((Decimal(c['amount_usd']) for c in charges if c['status'] == 'settled' and c['purpose'] == p), Decimal(0)) for p in ('generation', 'review', 'adjudication')}
    held = sum((Decimal(c['amount_usd']) for c in charges if c['status'] == 'held'), Decimal(0))
    unknown = sum(c['status'] == 'unknown' for c in charges)
    covered = {c['operation_id'] for c in charges}
    operations = {r['operation_id'] for r in rows}
    result['cohort_spending'] = {**{p + '_usd': str(v) for p, v in totals.items()}, 'held_usd': str(held), 'unknown_charges': unknown, 'unattributed_operations': len(operations - covered)}
    # Explicitly complete settled records are required; absence is not a zero bill.
    if not evidence['charges_complete'] or unknown or any(c['status'] == 'held' for c in charges) or covered != operations:
        return result
    total = sum(totals.values())
    # Operation can cover multiple findings. Allocate once over its mapped denominator.
    per_finding = []
    for operation in operations:
        denominator = sum(r['operation_id'] == operation for r in rows)
        cost = sum((Decimal(c['amount_usd']) for c in charges if c['operation_id'] == operation), Decimal(0))
        per_finding.append(cost / denominator)
    result.update(expected_provider_cost_range_usd=[str(min(per_finding) * eligible_findings), str(max(per_finding) * eligible_findings)],
                  cost_range_kind='observed_per_finding_min_max_scaled', cost_reason=None,
                  observed_cost_per_usable_outcome_usd=str(total / usable) if usable else None,
                  cost_uncertainty='Observed evaluated finding cost range, including unsuccessful attempts; not a price guarantee.')
    return result
