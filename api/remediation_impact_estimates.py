"""Conservative, read-only estimates from a versioned, validated evaluation cohort.

Callers must load evaluation metadata and samples from trusted, owner-scoped storage,
not accept them from a run-policy request. Live proposal counts, model self-confidence
and reviewer agreement alone are not calibration. This module performs no inference calls.
Rates are fractions (0..1), not percentages. A reliability interval is cohort evidence,
not the probability that a particular proposal is correct or permission to apply it.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import sqrt

MINIMUM_SAMPLES = 30
CONFIDENCE_LEVEL = 0.95

# Keep the machine reason and the user-facing explanation together.  The estimate
# remains fail-closed; this metadata only tells the planner what evidence is
# missing and never turns a missing estimate into a forecast.
_READINESS = {
    'calibration_unavailable': ('Evaluation not configured',
                                'No independent evaluation has been supplied for this change type and model configuration.',
                                ('Run a representative evaluation before using an impact estimate.')),
    'unsupported_cohort': ('No matching evaluation',
                           'The available evaluation covers a different change type or model configuration.',
                           ('Evaluate the selected change type with the active configuration.')),
    'calibration_not_validated': ('Evaluation needs validation',
                                  'The evaluation is present but has not been independently validated.',
                                  ('Complete independent validation before publishing an estimate.')),
    'incomplete_evaluation_population': ('Evaluation is incomplete',
                                         'The evaluation does not account for every case in its declared population.',
                                         ('Finish and reconcile the evaluation population.')),
    'invalid_evaluation_policy': ('Evaluation policy is invalid',
                                  'The configured evidence policy cannot be applied safely.',
                                  ('Use the server evidence policy and retry the evaluation.')),
    'invalid_evaluation_dates': ('Evaluation dates are invalid',
                                 'The evaluation timestamps are missing, contradictory, or in the future.',
                                 ('Correct the evaluation timestamps before publishing an estimate.')),
    'calibration_expired': ('Evaluation has expired',
                            'The evaluation is outside the allowed freshness window.',
                            ('Run a current evaluation for this change type and configuration.')),
    'samples_unavailable': ('Evaluation cases unavailable',
                            'The independent evaluation cases could not be read.',
                            ('Restore access to the evaluation evidence and retry.')),
    'invalid_sample_evidence': ('Evaluation evidence is invalid',
                                'At least one case is missing a required identity, outcome, or timestamp.',
                                ('Repair the case evidence and reconcile the population.')),
    'conflicting_sample_evidence': ('Evaluation evidence conflicts',
                                    'The same independent case has more than one recorded outcome.',
                                    ('Resolve the conflicting case before publishing an estimate.')),
    'insufficient_samples': ('Evaluation needs more cases',
                             'The independent evaluation has fewer cases than the minimum evidence policy.',
                             ('Evaluate more representative cases before using an impact estimate.')),
}


def estimate_readiness(reason=None, *, available=False):
    """Return safe, user-facing readiness metadata for an impact estimate.

    ``reason`` remains the stable machine value.  The additional fields are
    deliberately explanatory only: callers must still gate execution on
    ``available`` and must never use this helper as evidence of reliability.
    """
    if available:
        return {
            'state': 'ready',
            'label': 'Validated estimate available',
            'detail': 'A complete, current independent evaluation matches this change type and model configuration.',
            'next_step': 'Use the estimate as planning context; it does not approve or guarantee a specific fix.',
            'reason': None,
        }
    label, detail, next_steps = _READINESS.get(
        reason,
        ('Estimate unavailable', 'The evidence required for a safe estimate is not available.',
         ('Continue with deterministic results and human review until evidence is available.',)),
    )
    return {'state': 'unavailable', 'label': label, 'detail': detail,
            'next_step': next_steps[0], 'reason': reason}


def _timestamp(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def wilson_interval(successes, total):
    """Two-sided 95% Wilson score interval for independent binary evaluation cases."""
    if isinstance(total, bool) or isinstance(successes, bool) or not isinstance(total, int) or not isinstance(successes, int) or total <= 0 or not 0 <= successes <= total:
        raise ValueError('Counts must be integers with 0 <= successes <= total and total > 0')
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    half = z * sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, centre - half), min(1.0, centre + half)]


def build_impact_estimate(samples, *, config_id, change_family, evaluation=None,
                          now=None, minimum_samples=MINIMUM_SAMPLES, max_age_days=30):
    """Evaluate a complete matching cohort; unavailable evidence never becomes zero.

    ``evaluation``: version, config_id (exact generator/reviewer configuration revision),
    change_family, validated=True, population_complete=True, population_size,
    evaluated_at, expires_at. Metadata must represent an independently labelled evaluation.
    Each sample: sample_id (independent case), config_id, change_family, evaluation_version,
    outcome ('success'/'failure'), evidence_id, proposal_version, source_revision, observed_at.
    Optional cost_usd requires cost_settled=True and cost_attribution='sample'. Shared calls
    must be allocated once upstream; this helper never divides or repeats their cost.
    Replayed identical samples are deduplicated; conflicting evidence fails closed.
    """
    result = {'available': False, 'reason': 'calibration_unavailable',
              'readiness': estimate_readiness('calibration_unavailable'), 'sample_size': 0,
              'config_id': config_id, 'change_family': change_family,
              'evaluation_version': None, 'reliability_lower_bound': None,
              'reliability_range': None, 'confidence_level': CONFIDENCE_LEVEL,
              'cost_range_usd': None, 'cost_reason': 'attributed_cost_unavailable',
              'cost_range_kind': 'observed_sample_min_max',
              'metric': 'independently_evaluated_success_rate',
              'method': 'wilson_score_95_two_sided', 'evaluated_at': None, 'expires_at': None}
    def unavailable(reason):
        return {**result, 'reason': reason, 'readiness': estimate_readiness(reason)}
    if not isinstance(evaluation, dict):
        return result
    if not config_id or not change_family or evaluation.get('config_id') != config_id or evaluation.get('change_family') != change_family:
        return unavailable('unsupported_cohort')
    if not isinstance(evaluation.get('version'), str) or not evaluation['version'].strip() or evaluation.get('validated') is not True:
        return unavailable('calibration_not_validated')
    result['evaluation_version'] = evaluation['version']
    if evaluation.get('population_complete') is not True:
        return unavailable('incomplete_evaluation_population')
    if isinstance(minimum_samples, bool) or not isinstance(minimum_samples, int) or minimum_samples < MINIMUM_SAMPLES or isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days <= 0:
        return unavailable('invalid_evaluation_policy')
    current = _timestamp(now) if now is not None else datetime.now(timezone.utc)
    evaluated = _timestamp(evaluation.get('evaluated_at'))
    expires = _timestamp(evaluation.get('expires_at'))
    if not current or not evaluated or not expires or expires <= evaluated or evaluated > current:
        return unavailable('invalid_evaluation_dates')
    if current >= expires or current - evaluated > timedelta(days=max_age_days):
        return unavailable('calibration_expired')
    result.update(evaluated_at=evaluated.isoformat(), expires_at=expires.isoformat())
    if not isinstance(samples, (list, tuple)):
        return unavailable('samples_unavailable')
    matched = {}
    for sample in samples:
        if not isinstance(sample, dict):
            return unavailable('invalid_sample_evidence')
        if sample.get('config_id') != config_id or sample.get('change_family') != change_family:
            continue
        if sample.get('evaluation_version') != evaluation['version']:
            continue
        if not all(isinstance(sample.get(key), str) and sample[key].strip() for key in ('sample_id', 'evidence_id', 'proposal_version', 'source_revision')):
            return unavailable('invalid_sample_evidence')
        observed = _timestamp(sample.get('observed_at'))
        if not observed or observed > evaluated or current - observed > timedelta(days=max_age_days) or sample.get('outcome') not in ('success', 'failure'):
            return unavailable('invalid_sample_evidence')
        identity = sample['sample_id']
        if identity in matched and matched[identity] != sample:
            return unavailable('conflicting_sample_evidence')
        matched[identity] = sample
    result['sample_size'] = len(matched)
    population_size = evaluation.get('population_size')
    if isinstance(population_size, bool) or not isinstance(population_size, int) or population_size != len(matched):
        return unavailable('incomplete_evaluation_population')
    if len(matched) < minimum_samples:
        return unavailable('insufficient_samples')
    successes = sum(sample['outcome'] == 'success' for sample in matched.values())
    interval = wilson_interval(successes, len(matched))
    result.update(available=True, reason=None, readiness=estimate_readiness(available=True), successes=successes,
                  reliability_lower_bound=interval[0], reliability_range=interval)
    costs = []
    for sample in matched.values():
        try:
            cost = Decimal(str(sample.get('cost_usd')))
        except (InvalidOperation, ValueError):
            break
        if not cost.is_finite() or cost < 0 or sample.get('cost_settled') is not True or sample.get('cost_attribution') != 'sample':
            break
        costs.append(cost)
    if len(costs) == len(matched):
        result.update(cost_range_usd=[str(min(costs)), str(max(costs))], cost_reason=None)
    return result
