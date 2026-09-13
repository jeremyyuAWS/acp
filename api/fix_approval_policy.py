"""Frozen criterion-level approval choices; never an automation capability grant."""
import re

REVIEW_REQUIRED = 'This criterion requires human approval under the saved run policy'


def normalize(value):
    if not isinstance(value, dict) or set(value) - {'mode', 'review_scs'}:
        raise ValueError('A fix approval mode and criterion list are required')
    mode = value.get('mode')
    if mode not in {'automatic', 'review', 'custom'}:
        raise ValueError('Fix approval mode must be automatic, review, or custom')
    selected = value.get('review_scs', [])
    if not isinstance(selected, list) or any(type(code) is not str for code in selected):
        raise ValueError('Review criteria must be a list of success criterion IDs')
    from assessment_policy import RULE_CATALOG, REVIEW_FORMATS
    known = {rule['id'] for rule in RULE_CATALOG} | set(REVIEW_FORMATS)
    codes = []
    for code in selected:
        code = re.sub(r'^(?:WCAG_?|SC_)', '', code).replace('_', '.')
        if code not in known:
            raise ValueError('Unknown review success criterion')
        codes.append(code)
    if mode != 'custom' and codes:
        raise ValueError('Criterion exceptions require custom approval mode')
    return {'mode': mode, 'review_scs': sorted(set(codes))}


def requires_review(policy, criterion):
    # Absence keeps immutable accepted runs and their historical authorization.
    if 'fix_approval_policy' not in policy:
        return False
    choice = normalize(policy['fix_approval_policy'])
    criterion = re.sub(r'^(?:WCAG_?|SC_)', '', str(criterion)).replace('_', '.')
    return choice['mode'] == 'review' or criterion in choice['review_scs']
