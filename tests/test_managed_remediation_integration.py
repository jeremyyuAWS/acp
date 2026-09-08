"""Exercise the worker-to-provider boundary with a real canonical queued run."""
import pytest
import httpx
import core
import handlers
import providers
from ai_run_policy import read_run_budget, optional_current_run_context


@pytest.mark.parametrize('amount,reason', [('0.00', 'ai_disabled_or_budget_zero'), ('1.00', 'verified_model_pricing_unavailable')])
def test_job_scope_guards_real_provider_entry_and_preserves_rule_work(isolated_store, monkeypatch, amount, reason):
    store = isolated_store
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON', raising=False)
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status) VALUES('managed','owner','done')")
    batch = store.enqueue_stage_batch('managed', 'remediate', 'remediate_file', [{
        'owner': 'owner', 'scan_id': 'managed', 'file': 'a.html',
        'remediation_impact_policy': {'rule_based': 2, 'ai': 1, 'ai_budget_usd': amount},
    }], snapshot_id='s', request_fingerprint='managed')
    job = store.get_job(batch['job_ids'][0])
    continued = []
    def work(payload, job):
        result = providers.text_generate('Propose a clearer label')
        assert result['deferred'] is True
        assert result['reason'] == reason
        continued.append('rule work proceeds')
    monkeypatch.setattr(handlers, '_remediate_file_with_policy', work)
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: pytest.fail('must not spend'))
    handlers._remediate_file(job['payload'], job)
    assert continued == ['rule work proceeds']
    assert optional_current_run_context() is None
    budget = read_run_budget(store, 'owner', 'managed', batch['batch_id'])
    assert budget['spent_units'] == budget['held_units'] == 0


def test_worker_rejects_a_cap_stripped_from_managed_payload(isolated_store, monkeypatch):
    from ai_spending_budget import BudgetError
    store = isolated_store
    monkeypatch.setattr(core, 'store', store)
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status) VALUES('managed','owner','done')")
    batch = store.enqueue_stage_batch('managed', 'remediate', 'remediate_file', [{
        'owner': 'owner', 'scan_id': 'managed', 'file': 'a.html',
        'remediation_impact_policy': {'rule_based': 2, 'ai': 1, 'ai_budget_usd': '0.00'},
    }], snapshot_id='s', request_fingerprint='managed')
    job = store.get_job(batch['job_ids'][0])
    payload = {**job['payload'], 'remediation_impact_policy': {'rule_based': 2, 'ai': 1}}
    monkeypatch.setattr(handlers, '_remediate_file_with_policy', lambda *a: pytest.fail('must not run ungoverned'))
    with pytest.raises(BudgetError):
        handlers._remediate_file(payload, job)
