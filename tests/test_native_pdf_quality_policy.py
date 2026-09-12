"""Quality profile is explicit, owner-scoped, frozen, and PDF-only authorization."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from ai_run_policy import normalize_run_policy, run_context
from ai_spending_budget import BudgetError
from remediation_impact_settings import (
    normalize_policy, read_impact_policy, save_impact_policy, snapshot_impact_policy,
)
from accepted_remediation_plan import read_accepted_plan
from routes.remediation_policy import ImpactPreviewRequest, ImpactSaveRequest
from test_ai_run_policy import seed

PROFILE = 'native-pdf-quality.v1'
BASE = {'rule_based': 2, 'ai': 1, 'ai_zone': 'any', 'ai_budget_usd': '10.00',
        'document_wide_ai': True, 'document_wide_input_mode': 'native_pdf'}


def test_absent_profile_preserves_exact_legacy_normalization():
    assert normalize_policy(BASE) == BASE
    assert normalize_run_policy(BASE) == {
        'ai': 1, 'ai_zone': 'any', 'ai_budget_usd': '10.00', 'cap_units': 10000000,
        'currency': 'USD', 'document_wide_ai': True, 'document_wide_input_mode': 'native_pdf'}
    assert normalize_run_policy({'rule_based': 2, 'ai': 1}) is None


@pytest.mark.parametrize('patch', [
    {'document_wide_model_profile': 'unknown'}, {'document_wide_model_profile': True},
    {'document_wide_model_profile': None}, {'document_wide_model_profile': ''},
    {'document_wide_ai': False}, {'ai': 0}, {'ai_zone': 'local'},
    {'document_wide_input_mode': 'extracted'}, {'ai_budget_usd': '0.00'},
])
def test_invalid_profile_combinations_rejected_at_both_boundaries(patch):
    selected = {**BASE, 'document_wide_model_profile': PROFILE, **patch}
    for normalize in (normalize_policy, normalize_run_policy):
        with pytest.raises(ValueError if normalize is normalize_policy else BudgetError):
            normalize(selected)


@pytest.mark.parametrize('missing', ['ai_budget_usd', 'document_wide_input_mode', 'document_wide_ai', 'ai_zone'])
def test_profile_cannot_supply_missing_consent(missing):
    selected = {**BASE, 'document_wide_model_profile': PROFILE}
    del selected[missing]
    for normalize in (normalize_policy, normalize_run_policy):
        with pytest.raises(ValueError if normalize is normalize_policy else BudgetError): normalize(selected)


def test_profile_and_ordinary_generation_chain_coexist_without_rewriting():
    chain = {'version': 1, 'steps': [
        {'step_id': 'primary', 'position': 0, 'provider': 'anthropic', 'model': 'claude-haiku-4-5-20251001', 'enabled': True, 'capabilities': ['text']},
        {'step_id': 'fallback_1', 'position': 1, 'provider': 'anthropic', 'model': 'claude-sonnet-5', 'enabled': True, 'capabilities': ['text']}]}
    selected = {**BASE, 'document_wide_model_profile': PROFILE, 'generation_chain': chain}
    original = deepcopy(selected)
    assert normalize_policy(selected) == original
    normalized = normalize_run_policy(selected)
    assert normalized['document_wide_model_profile'] == PROFILE
    assert normalized['generation_chain'] == chain
    assert selected == original


def test_api_model_preserves_profile_and_rejects_nonstrings():
    assert ImpactPreviewRequest(**BASE, document_wide_model_profile=PROFILE).model_dump(exclude_none=True)['document_wide_model_profile'] == PROFILE
    assert ImpactSaveRequest(**BASE, expected_revision=0, document_wide_model_profile=PROFILE).document_wide_model_profile == PROFILE
    with pytest.raises(ValidationError):
        ImpactPreviewRequest(document_wide_model_profile=True)


def test_profile_persists_into_frozen_run_and_accepted_plan(isolated_store):
    store = isolated_store
    seed(store)
    selected = {**BASE, 'document_wide_model_profile': PROFILE}
    save_impact_policy(store, 'owner', 'owner', selected, 0)
    assert read_impact_policy(store, 'owner')['document_wide_model_profile'] == PROFILE
    assert 'document_wide_model_profile' not in read_impact_policy(store, 'other')
    policy = snapshot_impact_policy(store, 'owner')
    plain = snapshot_impact_policy(store, 'owner', BASE)
    assert policy['snapshot_id'] != plain['snapshot_id']
    run = store.enqueue_stage_batch('scan', 'remediate', 'remediate_file', [{
        'owner': 'owner', 'scan_id': 'scan', 'file': 'a.pdf', 'remediation_impact_policy': policy,
    }], snapshot_id='snapshot', request_fingerprint='quality-profile')
    job = store.get_job(run['job_ids'][0])
    with run_context(store, job['payload'], job) as ctx:
        assert ctx.policy['document_wide_model_profile'] == PROFILE
    # Changing current defaults must not change the accepted execution.
    save_impact_policy(store, 'owner', 'owner', BASE, 1)
    accepted = read_accepted_plan(store, 'owner', 'scan', run['batch_id'])
    assert accepted['policy']['document_wide_model_profile'] == PROFILE
    assert read_accepted_plan(store, 'other', 'scan', run['batch_id']) is None
    changed = deepcopy(job['payload'])
    if isinstance(changed, str): changed = json.loads(changed)
    del changed['remediation_impact_policy']['document_wide_model_profile']
    with pytest.raises(BudgetError):
        with run_context(store, changed, job): pass


def test_explicitly_clearing_profile_allows_other_modes(isolated_store):
    selected = {**BASE, 'document_wide_model_profile': PROFILE}
    save_impact_policy(isolated_store, 'owner', 'owner', selected, 0)
    # API rejects stale fields; clients clear incompatible selections explicitly.
    next_policy = {'rule_based': 2, 'ai': 0}
    save_impact_policy(isolated_store, 'owner', 'owner', next_policy, 1)
    assert read_impact_policy(isolated_store, 'owner') == {**next_policy, 'revision': 2}


def test_invalid_profile_api_returns_422_without_saving(isolated_store, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException, Response
    import core
    from routes.remediation_policy import remediation_impact_preview, save_remediation_impact_policy
    store = isolated_store
    seed(store)
    monkeypatch.setattr(core, 'store', store)
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner'))
    selection = {**BASE, 'document_wide_model_profile': 'unsupported'}
    with pytest.raises(HTTPException) as preview:
        remediation_impact_preview('scan', ImpactPreviewRequest(**selection), request, Response())
    assert preview.value.status_code == 422
    with pytest.raises(HTTPException) as save:
        save_remediation_impact_policy('scan', ImpactSaveRequest(**selection, expected_revision=0), request)
    assert save.value.status_code == 422
    assert read_impact_policy(store, 'owner')['revision'] == 0
