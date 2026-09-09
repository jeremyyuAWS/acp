"""Run-snapshotted review preferences; model agreement never bypasses validation."""
from __future__ import annotations

DEFAULT = {"enabled": False, "mode": "review_all", "minimum_reliability": 95,
           "max_review_attempts": 1, "review_model": "strong"}


def normalize_review_policy(value):
    if value is None:
        return dict(DEFAULT)
    if not isinstance(value, dict) or set(value) - set(DEFAULT):
        raise ValueError("Invalid AI review policy")
    result = {**DEFAULT, **value}
    if type(result['enabled']) is not bool or result['mode'] not in ('review_all', 'threshold'):
        raise ValueError("Choose review all or a validated review threshold")
    if type(result['minimum_reliability']) is not int or not 90 <= result['minimum_reliability'] <= 100:
        raise ValueError("Minimum validated reliability must be an integer from 90 to 100")
    if type(result['max_review_attempts']) is not int or result['max_review_attempts'] not in (1, 2):
        raise ValueError("Allow one review, or one review and one final review")
    if result['review_model'] not in ('strong', 'low_cost'):
        raise ValueError("Choose the strongest reviewer or the low-cost reviewer")
    if result['mode'] == 'threshold' and not result['enabled']:
        raise ValueError("An AI reviewer is required for a threshold policy")
    return result


def approval_gate(policy, *, review, estimate, validation, proposal_sha256,
                  source_revision, supported=False, administrator_floor=95):
    """Only server-produced evidence may be supplied; no model confidence inputs.

    Current generic text drafting supplies supported=False. A future supported
    writer must bind its independent validator and current source/version here.
    """
    p = normalize_review_policy(policy)
    reason = None
    if p['mode'] != 'threshold':
        reason = 'review_all_selected'
    elif supported is not True:
        reason = 'automatic_application_not_supported_for_this_change'
    elif not proposal_sha256 or not source_revision:
        reason = 'source_or_proposal_identity_missing'
    elif (not isinstance(review, dict) or review.get('verdict') != 'accept'
          or review.get('proposal_sha256') != proposal_sha256):
        reason = 'review_missing_disagreed_or_stale'
    elif (not isinstance(validation, dict) or validation.get('passed') is not True
          or validation.get('proposal_sha256') != proposal_sha256
          or validation.get('source_revision') != source_revision):
        reason = 'validation_missing_failed_or_stale'
    elif not isinstance(estimate, dict) or estimate.get('available') is not True:
        reason = 'calibration_unavailable'
    else:
        lower = estimate.get('reliability_lower_bound')
        if type(lower) not in (int, float) or not 0 <= lower <= 1:
            reason = 'calibration_unavailable'
        elif lower * 100 < max(administrator_floor, p['minimum_reliability']):
            reason = 'below_review_threshold'
    return {'approval_required': reason is not None, 'reason': reason or 'eligible_under_run_policy'}


def capabilities():
    return {'review_supported': True, 'automatic_application_supported': False,
            'review_models': ['strong', 'low_cost'],
            'threshold_minimum': 90, 'administrator_floor': 95,
            'reason': 'AI review can check a suggestion. Low-cost review is available; automatic application still requires a supported writer, independent checks and current calibration.'}
