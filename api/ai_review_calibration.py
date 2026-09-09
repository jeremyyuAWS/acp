"""Operator-ingested, immutable evaluation cohorts. Never calls a model/provider.

Reliability uses the lower endpoint of the two-sided 95% Wilson score interval
(z=1.959963984540054). A cohort is evidence about a population, not a proposal.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import datetime, timezone

SCHEMA_VERSION = 'ai-review-calibration.v1'
METHOD = 'wilson_95_two_sided_lower'
CONFIG_FIELDS = ('format', 'change_family', 'generator_provider', 'generator_model',
                 'reviewer_provider', 'reviewer_model', 'validator_version')
ADMIN_KEY = 'ai_review_calibration_admin.v1'


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('An explicit UTC evaluation timestamp is required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('Evaluation timestamps must include UTC timezone')
    return parsed


def wilson_lower(successes, sample_size):
    if type(sample_size) is not int or type(successes) is not int or not 0 <= successes <= sample_size or sample_size < 1:
        raise ValueError('Invalid independent evaluation sample counts')
    z = 1.959963984540054
    p = successes / sample_size
    return max(0.0, (p + z*z/(2*sample_size) - z*math.sqrt(p*(1-p)/sample_size + z*z/(4*sample_size**2))) / (1+z*z/sample_size))


def config_id(record):
    values = {}
    for field in CONFIG_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError('Missing or invalid evaluation configuration: ' + field)
        values[field] = value
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def normalize_evaluation(value):
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Unsupported calibration schema version')
    result = dict(value)
    version = value.get('evaluation_version')
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', version):
        raise ValueError('Invalid immutable evaluation version')
    timestamp(value.get('evaluated_at'))
    provenance = value.get('provenance', {})
    if not isinstance(provenance, dict) or provenance.get('kind') not in ('evaluated', 'synthetic'):
        raise ValueError('Explicit evaluated or synthetic provenance required')
    for key in ('dataset_sha256', 'evaluation_report_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', str(provenance.get(key, ''))):
            raise ValueError('Evaluation requires dataset and report SHA256 evidence')
    # Raw independent human/objective judgments, never the generating model's score.
    samples = value.get('samples')
    if not isinstance(samples, list) or not samples:
        raise ValueError('Independent evaluation samples are required')
    ids = set()
    for row in samples:
        if (not isinstance(row, dict) or not isinstance(row.get('sample_id'), str)
                or not row['sample_id'].strip() or row['sample_id'] in ids
                or type(row.get('passed')) is not bool
                or row.get('judgment_origin') not in ('independent_human', 'objective_validator')
                or not isinstance(row.get('evidence_ref'), str) or not row['evidence_ref'].strip()):
            raise ValueError('Samples require unique identities, independent judgments and evidence')
        ids.add(row['sample_id'])
    result['config_id'] = config_id(value)
    result['sample_size'] = len(samples)
    result['successes'] = sum(row['passed'] for row in samples)
    result['statistical_method'] = METHOD
    result['reliability_lower_bound'] = wilson_lower(result['successes'], len(samples))
    if 'impact_evidence' in value:
        from remediation_cohort_estimates import normalize_impact_evidence
        result['impact_evidence'] = normalize_impact_evidence(value['impact_evidence'])
    return result


def _key(owner, version):
    return 'ai_review_calibration:' + hashlib.sha256(owner.encode()).hexdigest() + ':' + version


def ingest_evaluation(store, owner, value):
    """Operator-only seam; replay identical evidence, reject version replacement."""
    result = normalize_evaluation(value)
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    key = _key(owner, result['evaluation_version'])
    with store._db.cursor() as cur:
        store._db.execute(cur, 'INSERT INTO app_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING', (key, encoded))
        store._db.execute(cur, 'SELECT value FROM app_settings WHERE key=%s', (key,))
        if store._db.fetchone(cur)['value'] != encoded:
            raise ValueError('Evaluation versions are immutable; ingest a new version')
    return result


def read_evaluation(store, owner, version):
    raw = store.get_setting(_key(owner, version))
    return json.loads(raw) if raw else None


def normalize_admin(value):
    if not isinstance(value, dict) or value.get('schema_version') != 'ai-review-admin.v1' or not isinstance(value.get('families'), dict):
        raise ValueError('Versioned administrator family configuration required')
    for family, rule in value['families'].items():
        if not isinstance(family, str) or not family or not isinstance(rule, dict):
            raise ValueError('Invalid permitted change family')
        floor = rule.get('minimum_reliability')
        if type(floor) not in (int, float) or not math.isfinite(floor) or not 0 <= floor <= 100:
            raise ValueError('Administrator minimum reliability must be 0–100')
        for key in ('minimum_sample_size', 'freshness_days'):
            if type(rule.get(key)) is not int or rule[key] < 1:
                raise ValueError('Positive sample size and freshness requirements required')
        if rule.get('writer_supported') is not True:
            raise ValueError('Only independently validated supported writer families may be permitted')
    return json.loads(json.dumps(value, allow_nan=False))


def read_admin(store):
    raw = store.get_setting(ADMIN_KEY)
    return normalize_admin(json.loads(raw)) if raw else {'schema_version':'ai-review-admin.v1', 'families':{}}


def applicable_evaluation(store, owner, version, configuration, rule, *, now=None):
    now = now or datetime.now(timezone.utc)
    record = read_evaluation(store, owner, version)
    reason = None
    if not record:
        reason = 'calibration_missing'
    else:
        try:
            record = normalize_evaluation(record)
            age = (now - timestamp(record['evaluated_at'])).total_seconds()
            if record['provenance']['kind'] != 'evaluated':
                reason = 'synthetic_calibration_not_eligible'
            elif (record['provenance'].get('representative') is not True
                  or record['provenance'].get('production_approved') is not True
                  or not isinstance(record['provenance'].get('approval_ref'), str)
                  or not record['provenance']['approval_ref'].strip()):
                reason = 'calibration_production_approval_missing'
            elif record['config_id'] != config_id(configuration):
                reason = 'calibration_configuration_mismatch'
            elif record['sample_size'] < rule['minimum_sample_size']:
                reason = 'calibration_sample_size_insufficient'
            elif age < 0 or age > rule['freshness_days'] * 86400:
                reason = 'calibration_expired_or_future'
        except (ValueError, KeyError, TypeError):
            reason = 'calibration_invalid'
    return {'available': reason is None, 'reason': reason, 'evaluation': record if reason is None else None}


def load_calibration_records(store, owner):
    prefix = 'ai_review_calibration:' + hashlib.sha256(owner.encode()).hexdigest() + ':'
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT value FROM app_settings WHERE key LIKE %s ORDER BY key', (prefix + '%',))
        rows = store._db.fetchall(cur)
    return [json.loads(row['value']) for row in rows]
