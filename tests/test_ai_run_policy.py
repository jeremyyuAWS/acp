"""Canonical queued run policies, transaction visibility and authenticated contexts."""
from concurrent.futures import ThreadPoolExecutor
import json
import os

import pytest

from ai_run_policy import (normalize_run_policy, run_context, read_run_budget,
                           current_run_context, optional_current_run_context)
from ai_spending_budget import BudgetError, AttemptConflict


def seed(store, owner="owner", scan="scan"):
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status) VALUES(%s,%s,'done')",
                          (scan, owner))


def enqueue(store, *, amount="0.10", ai=1, owner="owner", scan="scan", files=("a.html",), fingerprint="f"):
    policy = {"ai": ai, "rule_based": 2, "snapshot_id": "fixture-snapshot"}
    if amount is not None:
        policy["ai_budget_usd"] = amount
    return store.enqueue_stage_batch(scan, "remediate", "remediate_file", [
        {"owner": owner, "scan_id": scan, "file": f, "remediation_impact_policy": policy}
        for f in files], snapshot_id="snapshot", request_fingerprint=fingerprint)


def test_budget_commits_with_jobs_and_replay_keeps_exposure(isolated_store):
    s = isolated_store
    seed(s)
    result = enqueue(s)
    status = read_run_budget(s, "owner", "scan", result["batch_id"])
    assert status["cap_units"] == 100000
    job = s.get_job(result["job_ids"][0])
    with run_context(s, job["payload"], job) as ctx:
        assert ctx.enabled
        assert current_run_context() is ctx
        ctx.ledger.reserve(ctx.owner_id, ctx.run_id, "attempt", 80000, "fixture")
    assert optional_current_run_context() is None
    assert enqueue(s)["batch_id"] == result["batch_id"]
    assert read_run_budget(s, "owner", "scan", result["batch_id"])["held_units"] == 80000


def test_changed_cap_on_same_execution_is_refused(isolated_store):
    seed(isolated_store)
    enqueue(isolated_store)
    with pytest.raises(AttemptConflict):
        enqueue(isolated_store, amount="1.00")
    with pytest.raises(AttemptConflict):
        enqueue(isolated_store, amount=None)


def test_mixed_policies_cannot_partially_enqueue(isolated_store):
    s = isolated_store
    seed(s)
    with pytest.raises(BudgetError):
        s.enqueue_stage_batch("scan", "remediate", "remediate_file", [
            {"file": "a", "remediation_impact_policy": {"ai": 1, "ai_budget_usd": "0.10"}},
            {"file": "b", "remediation_impact_policy": {"ai": 1, "ai_budget_usd": "0.20"}}],
            snapshot_id="s", request_fingerprint="f")
    with s._db.cursor() as cur:
        for table in ("jobs", "ai_spending_budgets", "ai_spending_run_policies"):
            s._db.execute(cur, f"SELECT COUNT(*) AS n FROM {table}")
            assert s._db.fetchone(cur)["n"] == 0


def test_enqueue_failure_rolls_back_budget_too(isolated_store):
    s = isolated_store
    seed(s)
    with pytest.raises(ValueError, match="duplicate"):
        enqueue(s, files=("a", "a"))
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT COUNT(*) AS n FROM ai_spending_budgets")
        assert s._db.fetchone(cur)["n"] == 0


@pytest.mark.parametrize("amount,ai,managed,enabled", [(None, 1, False, False),
    ("0.00", 1, True, False), ("0.10", 0, True, False), ("0.10", 2, True, True)])
def test_legacy_zero_and_disabled_policies_are_distinct(isolated_store, amount, ai, managed, enabled):
    s = isolated_store
    seed(s)
    result = enqueue(s, amount=amount, ai=ai)
    job = s.get_job(result["job_ids"][0])
    with run_context(s, job["payload"], job) as ctx:
        assert (ctx is not None) == managed
        if managed:
            assert ctx.enabled == enabled
        else:
            with pytest.raises(BudgetError):
                current_run_context()


@pytest.mark.parametrize("field,value", [("owner", "intruder"), ("scan_id", "other"),
                                       ("file", "other.html")])
def test_worker_cannot_substitute_identity(isolated_store, field, value):
    s = isolated_store
    seed(s)
    job = s.get_job(enqueue(s)["job_ids"][0])
    payload = {**job["payload"], field: value}
    with pytest.raises(BudgetError):
        with run_context(s, payload, job):
            pytest.fail("untrusted context accepted")


def test_worker_cannot_substitute_cap_or_skip_canonical_job(isolated_store):
    s = isolated_store
    seed(s)
    job = s.get_job(enqueue(s)["job_ids"][0])
    payload = {**job["payload"], "remediation_impact_policy": {"ai": 1, "ai_budget_usd": "9.00"}}
    with pytest.raises(BudgetError):
        with run_context(s, payload, job):
            pass
    with pytest.raises(BudgetError):
        with run_context(s, job["payload"], {"id": "unknown"}):
            pass


def test_status_owner_scope_and_context_cleanup(isolated_store):
    s = isolated_store
    seed(s)
    result = enqueue(s)
    assert read_run_budget(s, "other", "scan", result["batch_id"]) is None
    assert read_run_budget(s, "owner", "other", result["batch_id"]) is None
    job = s.get_job(result["job_ids"][0])
    with pytest.raises(RuntimeError):
        with run_context(s, job["payload"], job) as ctx:
            with pytest.raises(TypeError):
                ctx.policy["cap_units"] = 999
            ctx.deferred.append({"reason": "unknown_price"})
            raise RuntimeError("handler failed")
    assert optional_current_run_context() is None


def test_contexts_do_not_leak_between_threads(isolated_store):
    s = isolated_store
    seed(s)
    result = enqueue(s, files=("a", "b"))
    def worker(jid):
        job = s.get_job(jid)
        with run_context(s, job["payload"], job) as ctx:
            ctx.deferred.append({"job": jid})
            assert len(ctx.deferred) == 1
        return optional_current_run_context()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(worker, result["job_ids"])) == [None, None]


@pytest.mark.parametrize("amount", [None, "", "1", "1.1", "01.00", "-1.00", "nan", 1.00, True])
def test_explicit_malformed_cap_never_becomes_legacy(amount):
    with pytest.raises(BudgetError):
        normalize_run_policy({"ai": 1, "ai_budget_usd": amount})


def test_context_rejects_outer_transaction(isolated_store):
    s = isolated_store
    seed(s)
    job = s.get_job(enqueue(s)["job_ids"][0])
    with s.transaction():
        with pytest.raises(BudgetError, match="ambient"):
            with run_context(s, job["payload"], job):
                pass


def test_no_job_id_legacy_fixture_needs_no_store_but_managed_does():
    with run_context(object(), {}, {}) as ctx:
        assert ctx is None
    with pytest.raises(BudgetError):
        with run_context(object(), {"remediation_impact_policy": {"ai": 1, "ai_budget_usd": "0.10"}}, {}):
            pass


def test_stripping_payload_cap_cannot_bypass_managed_context(isolated_store):
    s = isolated_store
    seed(s)
    job = s.get_job(enqueue(s)["job_ids"][0])
    payload = {**job["payload"], "remediation_impact_policy": {"ai": 1}}
    with pytest.raises(BudgetError):
        with run_context(s, payload, job):
            pass
    with s._db.cursor() as cur:
        s._db.execute(cur, "UPDATE jobs SET payload=%s WHERE id=%s", (json.dumps(payload), job["id"]))
    with pytest.raises(AttemptConflict):
        with run_context(s, payload, job):
            pass


def test_durable_policy_tampering_cannot_replenish_budget(isolated_store):
    s = isolated_store
    seed(s)
    result = enqueue(s)
    job = s.get_job(result["job_ids"][0])
    job["payload"]["remediation_impact_policy"]["ai_budget_usd"] = "1.00"
    with s._db.cursor() as cur:
        s._db.execute(cur, "UPDATE jobs SET payload=%s WHERE id=%s",
                      (json.dumps(job["payload"]), job["id"]))
    with pytest.raises(AttemptConflict):
        with run_context(s, job["payload"], job):
            pass


def test_owner_reset_removes_only_owners_budget(isolated_store):
    s = isolated_store
    seed(s)
    seed(s, owner="other", scan="other-scan")
    first = enqueue(s)
    other = enqueue(s, owner="other", scan="other-scan")
    s.reset_user_data("owner")
    assert read_run_budget(s, "owner", "scan", first["batch_id"]) is None
    assert read_run_budget(s, "other", "other-scan", other["batch_id"]) is not None
    s.reset_analytics()
    with s._db.cursor() as cur:
        for table in ("ai_spending_attempts", "ai_spending_run_policies", "ai_spending_budgets"):
            s._db.execute(cur, f"SELECT COUNT(*) AS n FROM {table}")
            assert s._db.fetchone(cur)["n"] == 0


@pytest.fixture
def postgres_store(monkeypatch):
    """Opt-in full versioned Store migration on a disposable local database only."""
    from urllib.parse import urlparse
    import store
    url = os.getenv("ACP_BUDGET_TEST_PG_URL")
    if not url:
        pytest.skip("requires disposable local Postgres")
    parsed = urlparse(url)
    assert parsed.hostname in ("localhost", "127.0.0.1") and parsed.path == "/acp_budget_test"
    monkeypatch.setattr(store, "_DATABASE_URL", url)
    result = store.Store()
    result.reset_analytics()
    yield result
    result.reset_analytics()
    if result._db._pool:
        result._db._pool.closeall()


@pytest.mark.parametrize("scenario", [test_budget_commits_with_jobs_and_replay_keeps_exposure,
    test_changed_cap_on_same_execution_is_refused, test_mixed_policies_cannot_partially_enqueue,
    test_enqueue_failure_rolls_back_budget_too, test_contexts_do_not_leak_between_threads,
    test_owner_reset_removes_only_owners_budget])
def test_postgres_run_integration(postgres_store, scenario):
    scenario(postgres_store)
