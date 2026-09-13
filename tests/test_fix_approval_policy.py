import pytest
from fix_approval_policy import normalize, requires_review
from remediation_impact_settings import normalize_policy
from ai_run_policy import normalize_run_policy
from remediation_impact_execution import execution_controls
from remediation_impact import _route


def test_custom_criterion_policy_is_preserved_in_both_saved_snapshots():
    policy = {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '1.00', 'auto_approve_ai': True,
              'fix_approval_policy': {'mode': 'custom', 'review_scs': ['WCAG_1_3_1', '1.3.1']}}
    expected = {'mode': 'custom', 'review_scs': ['1.3.1']}
    assert normalize_policy(policy)['fix_approval_policy'] == expected
    assert normalize_run_policy(policy)['fix_approval_policy'] == expected
    assert requires_review(policy, 'SC_1_3_1')
    assert not requires_review(policy, '1.1.1')


@pytest.mark.parametrize('value', [None, {'mode': 'wrong'}, {'mode': 'custom', 'review_scs': ['99.99.99']}, {'mode': 'automatic', 'review_scs': ['1.3.1']}, {'mode': 'custom', 'review_scs': [True]}, {'mode': 'review', 'enable_unsupported': True}])
def test_invalid_policy_fails_closed(value):
    with pytest.raises(ValueError):
        normalize(value)


def test_absent_choice_preserves_existing_policy_without_adding_keys():
    original = {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '1.00'}
    assert 'fix_approval_policy' not in normalize_policy(original)
    assert 'fix_approval_policy' not in normalize_run_policy(original)
    assert not requires_review(original, '1.3.1')


def test_custom_criterion_stops_even_forged_automatic_writer_whitelist():
    policy = {'rule_based': 2, 'ai': 1, 'fix_approval_policy': {'mode':'custom', 'review_scs':['1.3.1']}}
    payload = {'remediation_impact_policy': policy, 'remediation_impact_allowed_rules': ['1.3.1', '1.4.3']}
    assert execution_controls(payload, True)['allowed_rules'] == frozenset({'1.4.3'})
    row = {'rule_id': '1.3.1', 'origin':'rule_based', 'remediation_supported':True}
    assert _route(row, policy) == ('review','criterion_approval_required')


def test_review_all_does_not_disable_generation_or_claim_unsupported_work_automatic():
    policy = {'rule_based':2, 'ai':1, 'fix_approval_policy': {'mode':'review', 'review_scs':[]}}
    controls = execution_controls({'remediation_impact_policy':policy, 'remediation_impact_allowed_rules':['1.1.1','1.3.1']}, True)
    assert not controls['allowed_rules']
    assert controls['draft_ai'] is True
    assert _route({'rule_id':'1.3.1','human_only':True}, policy) == ('manual','accessibility_judgment')
