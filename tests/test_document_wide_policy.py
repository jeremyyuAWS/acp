"""Document-wide consent survives admission and immutable execution snapshots."""
import pytest
from pydantic import ValidationError
from routes.remediation_policy import ImpactPreviewRequest
from remediation_impact_settings import normalize_policy, save_impact_policy, read_impact_policy, snapshot_impact_policy
from ai_run_policy import normalize_run_policy
from ai_spending_budget import BudgetError

BASE = {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '1.00'}

@pytest.mark.parametrize('enabled', [True, False])
def test_roundtrip(isolated_store, enabled):
    policy = ImpactPreviewRequest(**BASE, document_wide_ai=enabled, ai_zone='any').model_dump(exclude_none=True, exclude={'scope'})
    saved = save_impact_policy(isolated_store, 'owner', 'owner', policy, 0)['policy']
    assert saved['document_wide_ai'] is enabled
    assert read_impact_policy(isolated_store, 'owner')['document_wide_ai'] is enabled
    snapshot = snapshot_impact_policy(isolated_store, 'owner')
    assert normalize_run_policy(snapshot)['document_wide_ai'] is enabled
    assert 'document_wide_ai' not in read_impact_policy(isolated_store, 'another-owner')


def test_absent_preserves_legacy_snapshot_and_explicit_changes_identity(isolated_store):
    assert 'document_wide_ai' not in normalize_policy(BASE)
    assert 'document_wide_ai' not in normalize_run_policy(BASE)
    old = snapshot_impact_policy(isolated_store, 'owner', BASE)
    new = snapshot_impact_policy(isolated_store, 'owner', {**BASE, 'document_wide_ai': True})
    assert old['snapshot_id'] != new['snapshot_id']


@pytest.mark.parametrize('value', ['true', 1, None, {}])
def test_strict_boolean(value):
    for normalize in (normalize_policy, normalize_run_policy):
        with pytest.raises((ValueError, BudgetError)):
            normalize({**BASE, 'document_wide_ai': value})
    if value is not None:
        with pytest.raises(ValidationError):
            ImpactPreviewRequest(**BASE, document_wide_ai=value)


@pytest.mark.parametrize('update', [{'ai': 0}, {'ai': 2}, {'ai_zone': 'local'}])
def test_reject_unexecutable_opt_in(update):
    for normalize in (normalize_policy, normalize_run_policy):
        with pytest.raises((ValueError, BudgetError)):
            normalize({**BASE, **update, 'document_wide_ai': True})


def test_requires_managed_budget():
    for normalize in (normalize_policy, normalize_run_policy):
        with pytest.raises((ValueError, BudgetError)):
            normalize({'rule_based': 2, 'ai': 1, 'document_wide_ai': True})


def test_api_preserves_local_only_consent():
    policy = ImpactPreviewRequest(**BASE, ai_zone='local').model_dump(exclude_none=True, exclude={'scope'})
    assert normalize_policy(policy)['ai_zone'] == 'local'
