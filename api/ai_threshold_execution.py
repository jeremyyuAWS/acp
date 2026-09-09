"""Server-only policy sealing and fail-closed per-version approval evaluation.

No request body, model score or mutable owner preference is execution authority.
The accepted managed run contains the sealed policy and pinned evaluation versions.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timezone

from ai_review_calibration import applicable_evaluation, read_admin, read_evaluation


def seal_policy(store, owner, selection, *, now=None):
    """Resolve administrator constraints and evaluated versions at run approval."""
    if selection.get('mode') != 'threshold':
        return None
    if selection.get('enabled') is not True:
        raise ValueError('Automatic application requires an explicitly selected reviewer')
    threshold = selection.get('minimum_reliability')
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValueError('Select minimum validated reliability; no default percentage is assumed')
    families = selection.get('permitted_families')
    versions = selection.get('evaluation_versions')
    if (not isinstance(families, list) or not families or any(not isinstance(f, str) for f in families)
            or len(set(families)) != len(families) or not isinstance(versions, dict)
            or set(versions) != set(families)):
        raise ValueError('Explicit permitted families and evaluation versions are required')
    admin = read_admin(store)
    sealed = {}
    for family in families:
        rule = admin['families'].get(family)
        if not rule or family not in SUPPORTED_WRITERS or threshold < rule['minimum_reliability']:
            raise ValueError('The change family is unavailable or its administrator minimum is not met')
        record = read_evaluation(store, owner, versions[family])
        if not record or record.get('change_family') != family:
            raise ValueError('Applicable calibration is missing')
        check = applicable_evaluation(store, owner, versions[family], record, rule, now=now)
        if not check['available']:
            raise ValueError(check['reason'])
        if check['evaluation']['reliability_lower_bound'] * 100 < threshold:
            raise ValueError('Evaluated reliability is below the selected threshold')
        sealed[family] = {'administrator':rule, 'evaluation_version':versions[family],
                          'configuration':{key:record[key] for key in (
                              'format','change_family','generator_provider','generator_model',
                              'reviewer_provider','reviewer_model','validator_version')}}
    result = {'schema_version':'ai-threshold-run-policy.v1', 'mode':'threshold',
              'minimum_reliability':threshold, 'families':sealed}
    canonical = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    result['policy_id'] = hashlib.sha256(canonical.encode()).hexdigest()
    return result


def read_run_policy(store, owner, scan_id, run_id):
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT policy_json FROM ai_spending_run_policies '
                          'WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (owner, scan_id, run_id))
        row = store._db.fetchone(cur)
    return json.loads(row['policy_json']).get('threshold_policy') if row else None


def evaluate_policy(store, owner, policy, evidence, *, now=None):
    """Evidence is an internal exact-version validator adapter result, never AI text.

    All gate results are retained for explanatory UI, including the first failure.
    Unknowns fail closed. Administrator tightening applies immediately; loosening
    cannot weaken the constraints frozen when this run was approved.
    """
    evidence = evidence if isinstance(evidence, dict) else {}
    checks = []
    def check(name, passed):
        checks.append({'gate':name, 'passed':passed is True})
    valid_policy = isinstance(policy, dict) and policy.get('schema_version') == 'ai-threshold-run-policy.v1' and policy.get('mode') == 'threshold'
    check('explicit_automatic_run_policy', valid_policy)
    policy = policy if valid_policy else {}
    family = evidence.get('change_family')
    binding = policy.get('families', {}).get(family, {})
    current = read_admin(store)['families'].get(family, {})
    check('permitted_supported_family', bool(binding and current and current.get('writer_supported') is True and evidence.get('supported') is True))
    digest, source = evidence.get('proposal_sha256'), evidence.get('source_sha256')
    check('exact_proposal_and_source_identity', bool(digest and source and evidence.get('snapshot_id')))
    review = evidence.get('review') or {}
    configuration = binding.get('configuration') or {}
    check('independent_exact_version_acceptance', bool(review.get('verdict') == 'accept'
          and review.get('proposal_sha256') == digest and review.get('source_sha256') == source
          and review.get('independent') is True and review.get('model') == configuration.get('reviewer_model')
          and review.get('provider') == configuration.get('reviewer_provider')
          and (review.get('provider'),review.get('model')) != (configuration.get('generator_provider'),configuration.get('generator_model'))))
    validation = evidence.get('validation') or {}
    check('objective_validation_passed', bool(validation.get('passed') is True
          and validation.get('objective') is True and validation.get('proposal_sha256') == digest
          and validation.get('source_sha256') == source
          and validation.get('validator_version') == configuration.get('validator_version')))
    check('required_source_evidence_present', evidence.get('source_evidence_complete') is True)
    check('source_unchanged', bool(source and evidence.get('current_source_sha256') == source))
    check('no_subjective_meaning_change', evidence.get('subjective') is False)
    check('no_unresolved_disagreement', evidence.get('disagreement') is False)
    check('no_hard_review_conditions', evidence.get('hard_review_conditions') == [])
    calibration = {'available':False, 'reason':'calibration_missing'}
    if binding and current:
        frozen = binding['administrator']
        rule = {**frozen, 'minimum_sample_size':max(frozen['minimum_sample_size'],current['minimum_sample_size']),
                'freshness_days':min(frozen['freshness_days'],current['freshness_days'])}
        calibration = applicable_evaluation(store, owner, binding['evaluation_version'], evidence.get('configuration', {}), rule, now=now)
    check('applicable_fresh_calibration', calibration['available'])
    record = calibration.get('evaluation') or {}
    lower = record.get('reliability_lower_bound')
    threshold = max(policy.get('minimum_reliability',100),binding.get('administrator',{}).get('minimum_reliability',100),current.get('minimum_reliability',100))
    check('validated_reliability_meets_threshold', type(lower) in (int,float) and lower * 100 >= threshold)
    failed = [row['gate'] for row in checks if not row['passed']]
    return {'approval_required':bool(failed), 'approval_kind':None if failed else 'policy',
            'reason':failed[0] if failed else 'eligible_under_run_policy', 'checks':checks,
            'calibration_reason':calibration.get('reason'), 'evaluation_version':binding.get('evaluation_version'),
            'reliability_lower_bound':lower, 'minimum_reliability':policy.get('minimum_reliability'),
            'policy_id':policy.get('policy_id'), 'snapshot_id':evidence.get('snapshot_id'),
            'proposal_sha256':digest, 'source_sha256':source,
            'status':'awaiting_human_review' if failed else 'approved_awaiting_completion'}


def evaluate_run_policy(store, owner, scan_id, run_id, evidence, *, now=None):
    return evaluate_policy(store, owner, read_run_policy(store, owner, scan_id, run_id), evidence, now=now)


# Code-owned: configuration cannot manufacture an objectively validated writer.
# Register only after exact structured review, source evidence and controlled
# apply/verify integration have qualifying fixtures. Generic drafts do not qualify.
SUPPORTED_WRITERS = {}


def apply_under_run_policy(store, owner, scan_id, run_id, snapshot_id, change_family, *, now=None):
    """Dispatch a registered controlled writer with replay fencing.

    Adapter.prepare reloads the immutable structured snapshot and current source,
    independent review and objective validation. Adapter.apply uses the existing
    controlled writer and verification/recovery path; it never marks a fix from
    approval alone. No adapters ship enabled until that complete proof exists.
    """
    adapter = SUPPORTED_WRITERS.get(change_family)
    if adapter is None:
        return {'approval_required':True, 'reason':'supported_objective_writer_unavailable',
                'status':'awaiting_human_review', 'checks':[{'gate':'registered_controlled_writer','passed':False}]}
    identity = [owner,scan_id,run_id,snapshot_id]
    key = 'ai_threshold_application:' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    # A retry cannot reapply, buy review calls or recover under newer preferences.
    raw = store.get_setting(key)
    if raw:
        receipt = json.loads(raw)
        return {**receipt, 'replayed':True}
    evidence = adapter.prepare(store, owner, scan_id, run_id, snapshot_id)
    if evidence.get('snapshot_id') != snapshot_id or evidence.get('change_family') != change_family:
        raise ValueError('Writer evidence does not identify the requested exact proposal')
    result = evaluate_run_policy(store, owner, scan_id, run_id, evidence, now=now)
    if result['approval_required']:
        return result
    receipt = {**result, 'receipt_id':key, 'status':'approved_awaiting_completion',
               'created_at':(now or datetime.now(timezone.utc)).isoformat()}
    encoded = json.dumps(receipt, sort_keys=True)
    with store._db.cursor() as cur:
        store._db.execute(cur,'INSERT INTO app_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING',(key,encoded))
        claimed = cur.rowcount == 1
    if not claimed:
        return {**json.loads(store.get_setting(key)), 'replayed':True}
    # Revalidate source and all hard gates at dispatch, after claiming the receipt.
    fresh = adapter.prepare(store, owner, scan_id, run_id, snapshot_id)
    gate = evaluate_run_policy(store, owner, scan_id, run_id, fresh, now=now)
    if (gate['approval_required'] or fresh.get('snapshot_id') != snapshot_id
            or fresh.get('change_family') != change_family
            or fresh.get('proposal_sha256') != evidence.get('proposal_sha256')
            or fresh.get('source_sha256') != evidence.get('source_sha256')):
        receipt = {**receipt, 'status':'awaiting_human_review', 'approval_required':True, 'approval_kind':None,
                   'checks':gate['checks'] + [{'gate':'exact_version_unchanged_before_write','passed':False}],
                   'reason':'evidence_changed_before_application'}
    else:
        try:
            outcome = adapter.apply(store, owner, scan_id, run_id, snapshot_id, receipt)
            # Exact artifact verification is the adapter's existing writer contract.
            verified = (isinstance(outcome,dict) and outcome.get('verified') is True
                        and outcome.get('snapshot_id') == snapshot_id
                        and outcome.get('proposal_sha256') == evidence['proposal_sha256']
                        and outcome.get('source_sha256') == evidence['source_sha256']
                        and bool(outcome.get('artifact_sha256')) and bool(outcome.get('verification_ref')))
            receipt = {**receipt, 'status':'fixed_and_checked' if verified else 'still_needs_work',
                       'verification':outcome, 'reason':'verified_under_run_policy' if verified else 'verification_failed_or_unavailable'}
        except Exception:
            # A possibly completed write cannot be replayed. Existing recovery must
            # reconcile its artifact before a new explicit operation is permitted.
            receipt = {**receipt,'status':'still_needs_work','reason':'application_requires_recovery'}
    store.set_setting(key,json.dumps(receipt,sort_keys=True))
    return receipt


def normalize_selection(value):
    """Public preferences contain selections only, never a server approval seal."""
    defaults = {'enabled':False,'mode':'review_all','minimum_reliability':None,
                'max_review_attempts':1,'review_model':'strong',
                'permitted_families':[],'evaluation_versions':{}}
    if value is None:
        return defaults
    if not isinstance(value,dict) or set(value)-set(defaults):
        raise ValueError('Invalid AI review policy')
    result = {**defaults,**value}
    if type(result['enabled']) is not bool or result['mode'] not in ('review_all','threshold'):
        raise ValueError('Choose review all or a validated review threshold')
    lower=result['minimum_reliability']
    if lower is not None and (type(lower) not in (int,float) or not math.isfinite(lower) or not 0 <= lower <= 100):
        raise ValueError('Minimum validated reliability must be from 0 to 100')
    if type(result['max_review_attempts']) is not int or result['max_review_attempts'] not in (1,2):
        raise ValueError('Allow one review, or one review and one final review')
    if result['review_model'] not in ('strong','low_cost'):
        raise ValueError('Choose the strongest reviewer or the low-cost reviewer')
    if result['mode']=='threshold' and not result['enabled']:
        raise ValueError('An AI reviewer is required for a threshold policy')
    families,versions=result['permitted_families'],result['evaluation_versions']
    if not isinstance(families,list) or any(not isinstance(f,str) or not f for f in families) or len(set(families))!=len(families):
        raise ValueError('Invalid permitted change families')
    if not isinstance(versions,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in versions.items()):
        raise ValueError('Invalid evaluation version selection')
    return json.loads(json.dumps(result,allow_nan=False))


def normalize_sealed_policy(value):
    """Validate queued server seal and copy its nested immutable contents."""
    if not isinstance(value,dict) or value.get('schema_version')!='ai-threshold-run-policy.v1' or value.get('mode')!='threshold':
        raise ValueError('Invalid approved threshold policy snapshot')
    result=json.loads(json.dumps(value,allow_nan=False))
    identity=result.pop('policy_id',None)
    canonical=json.dumps(result,sort_keys=True,separators=(',', ':'),allow_nan=False)
    if identity != hashlib.sha256(canonical.encode()).hexdigest():
        raise ValueError('Approved threshold policy snapshot changed')
    if not result.get('families'):
        raise ValueError('An approved threshold policy must name permitted families')
    result['policy_id']=identity
    return result


def capability_summary(store=None, owner=None, *, now=None):
    result={'review_supported':True,'automatic_application_supported':False,
            'review_models':['strong','low_cost'],'threshold_minimum':None,
            'administrator_floor':None,'eligible_families':[],
            'reason':'Available after validation is configured. A supported objective writer, exact-version independent review and current evaluated reliability are required.'}
    if store is None or not owner or not SUPPORTED_WRITERS:
        return result
    from ai_review_calibration import load_calibration_records
    admin=read_admin(store)
    for record in load_calibration_records(store,owner):
        family=record.get('change_family');rule=admin['families'].get(family)
        if not rule or family not in SUPPORTED_WRITERS:
            continue
        check=applicable_evaluation(store,owner,record['evaluation_version'],record,rule,now=now)
        if not check['available'] or check['evaluation']['reliability_lower_bound']*100 < rule['minimum_reliability']:
            continue
        result['eligible_families'].append({'change_family':family,'format':record['format'],
            'evaluation_version':record['evaluation_version'],'config_id':record['config_id'],
            'minimum_reliability':rule['minimum_reliability'],
            'reliability_lower_bound':check['evaluation']['reliability_lower_bound'],
            'reviewer_model':record['reviewer_model'],'reviewer_provider':record['reviewer_provider']})
    if result['eligible_families']:
        result.update(automatic_application_supported=True,reason='Choose explicit change families and a reliability threshold. Every finding must still pass all policy gates.')
    return result
