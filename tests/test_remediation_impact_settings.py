import pytest

from remediation_impact_settings import (
    ImpactPolicyConflict, read_impact_policy, save_impact_policy, snapshot_impact_policy,
)


def test_defaults_are_owner_scoped_and_do_not_change_global_ai(isolated_store):
    store = isolated_store
    store.set_ai_enabled(False)
    result = save_impact_policy(store, 'alice', 'alice', {'rule_based': 0, 'ai': 0}, 0)
    assert result['policy'] == {'rule_based': 0, 'ai': 0, 'revision': 1}
    assert read_impact_policy(store, 'bob') == {'rule_based': 2, 'ai': 1, 'revision': 0}
    assert store.get_ai_enabled() is False


def test_stale_edits_conflict_but_identical_retry_is_safe(isolated_store):
    store = isolated_store
    selected = {'rule_based': 1, 'ai': 0}
    save_impact_policy(store, 'alice', 'alice', selected, 0)
    assert save_impact_policy(store, 'alice', 'alice', selected, 0)['duplicate'] is True
    with pytest.raises(ImpactPolicyConflict):
        save_impact_policy(store, 'alice', 'alice', {'rule_based': 0, 'ai': 0}, 0)


def test_preview_execution_snapshot_does_not_save_defaults(isolated_store):
    store = isolated_store
    first = snapshot_impact_policy(store, 'alice', {'rule_based': 0, 'ai': 0})
    assert first == snapshot_impact_policy(store, 'alice', {'rule_based': 0, 'ai': 0})
    assert first['snapshot_id'] != snapshot_impact_policy(store, 'alice')['snapshot_id']
    assert read_impact_policy(store, 'alice')['revision'] == 0


def test_saving_displayed_defaults_activates_policy_for_other_entry_points(isolated_store):
    result = save_impact_policy(isolated_store, 'alice', 'alice', {'rule_based': 2, 'ai': 1}, 0)
    assert result['policy']['revision'] == 1
    assert read_impact_policy(isolated_store, 'alice')['revision'] == 1


@pytest.mark.parametrize('policy', [
    {'rule_based': True, 'ai': 0}, {'rule_based': -1, 'ai': 0},
    {'rule_based': 2, 'ai': 2}, {'rule_based': 2, 'ai': 3},
])
def test_unsupported_or_invalid_policies_never_save(isolated_store, policy):
    with pytest.raises(ValueError):
        save_impact_policy(isolated_store, 'alice', 'alice', policy, 0)
    assert read_impact_policy(isolated_store, 'alice')['revision'] == 0


def test_budget_is_canonical_owner_scoped_and_changes_execution_identity(isolated_store):
    selected = {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '1.5'}
    saved = save_impact_policy(isolated_store, 'alice', 'alice', selected, 0)
    assert saved['policy']['ai_budget_usd'] == '1.50'
    assert read_impact_policy(isolated_store, 'alice')['ai_budget_usd'] == '1.50'
    assert 'ai_budget_usd' not in read_impact_policy(isolated_store, 'bob')
    first = snapshot_impact_policy(isolated_store, 'alice')
    same = snapshot_impact_policy(isolated_store, 'alice', {**selected, 'ai_budget_usd': '1.50'})
    changed = snapshot_impact_policy(isolated_store, 'alice', {**selected, 'ai_budget_usd': '2.00'})
    assert first == same
    assert first['snapshot_id'] != changed['snapshot_id']


@pytest.mark.parametrize('amount', ['', '-1', 'NaN', 'Infinity', '1.001', '1e2', '1000000.01', 1, True, None])
def test_invalid_budget_rejected_before_policy_persistence(isolated_store, amount):
    with pytest.raises(ValueError):
        save_impact_policy(isolated_store, 'alice', 'alice',
                           {'rule_based': 2, 'ai': 1, 'ai_budget_usd': amount}, 0)
    assert read_impact_policy(isolated_store, 'alice')['revision'] == 0


def test_removing_saved_budget_is_not_an_identical_retry(isolated_store):
    capped = {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '1.00'}
    save_impact_policy(isolated_store, 'alice', 'alice', capped, 0)
    with pytest.raises(ImpactPolicyConflict):
        save_impact_policy(isolated_store, 'alice', 'alice', {'rule_based': 2, 'ai': 1}, 0)
