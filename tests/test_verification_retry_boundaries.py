"""Integration boundaries for the existing opt-in HTML verification waterfall.

These fixtures do not assert that ordinary Office/PDF saved-fix failures invoke
this waterfall: that wiring is absent. Model callbacks are synthetic, while
reservation/settlement and independent candidate verification are real.
"""
from copy import deepcopy

import pytest

from ai_spending_budget import BudgetLedger
from llm_remediation_waterfall import BudgetAdapter
from store import _SQLiteAdapter
from test_llm_remediation_waterfall import Harness


def ledger_for(tmp_path, cap=100_000, *, prices=None):
    ledger = BudgetLedger(_SQLiteAdapter(str(tmp_path / "retry-budget.db")))
    ledger.init_schema()
    ledger.create_budget("owner", "run", cap)
    budget = BudgetAdapter(ledger, "owner", "run", prices if prices is not None
                           else {"small": "fixture-small-v1", "large": "fixture-large-v1"})
    return ledger, dict(reserve=budget.reserve, claim_dispatch=budget.claim_dispatch,
                       settle=budget.settle, mark_uncertain=budget.mark_uncertain)


@pytest.mark.parametrize("boundary", ["remaining_budget", "missing_stronger_price"])
def test_failed_verification_does_not_authorize_unfunded_stronger_model(tmp_path, boundary):
    ledger, callbacks = ledger_for(tmp_path,
        cap=20_000 if boundary == "remaining_budget" else 100_000,
        prices={"small": "fixture-small-v1"} if boundary == "missing_stronger_price" else None)
    h = Harness()
    h.languages = ["fr", "en"]
    result = h.run(**callbacks)

    # The first candidate actually fails the independent verifier. Its known
    # charge remains settled; that failure creates neither budget nor pricing.
    assert result["attempts"][0]["status"] == "rejected"
    assert result["attempts"][0]["evidence"]["issue_resolved"] is False
    assert h.calls == [("generate", "small")]
    assert result["status"] == "exception"
    assert result["candidate"] is None
    assert result["reasons"][-1].startswith("cost_failure:")
    snapshot = ledger.snapshot("owner", "run")
    assert snapshot["spent_units"] == 10_000
    assert snapshot["held_units"] == 0
    assert not snapshot["blocked"]


@pytest.mark.parametrize("crash_stage", ["dispatching", "generating"])
def test_interrupted_stronger_attempt_preserves_charge_exposure_without_redispatch(tmp_path, crash_stage):
    ledger, callbacks = ledger_for(tmp_path)
    h = Harness()
    h.languages = ["fr", "en"]

    def persist(state):
        if len(state["attempts"]) == 2 and state["attempts"][-1]["status"] == crash_stage:
            raise OSError("fixture durable snapshot failure")
        h.persist(state)

    with pytest.raises(OSError, match="snapshot failure"):
        h.run(**callbacks, persist=persist)
    assert h.calls == [("generate", "small")]
    before = ledger.snapshot("owner", "run")
    assert before["spent_units"] == 10_000
    assert before["held_units"] == 50_000

    # Restart from the last genuinely saved snapshot, not the attempted failed
    # save. Even a reserved-but-not-called fallback requires reconciliation.
    resumed = Harness()
    result = resumed.run(**callbacks, previous=deepcopy(h.snapshots[-1]))
    assert result["status"] == "exception"
    assert result["candidate"] is None
    assert result["reasons"][-1].startswith("interrupted_attempt:")
    assert resumed.calls == []
    assert ledger.snapshot("owner", "run") == before
