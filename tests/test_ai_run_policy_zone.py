"""`ai_zone`: where a run's AI may process, and what that changes about the budget gate.

Standing approval authorizes applying available suggestions; it does not authorize
spending. A zero-budget cloud run may retain that permission while RunContext.enabled
continues to block cloud generation. Local-only runs may draft without cloud charges.

The absent case is the one that has to be watched: `persist_run_policy` compares the
canonical JSON of a re-normalized policy against the stored one and raises
`AttemptConflict` on any difference, so adding a key to an old snapshot's normalized form
would reject accepted runs. Hence `test_absent_zone_round_trips_byte_identically`.
"""
import json

import pytest

from ai_run_policy import AI_ZONES, RunContext, normalize_run_policy
from ai_spending_budget import BudgetError

BASE = {"ai": 1, "ai_budget_usd": "1.00"}
ZERO = {"ai": 1, "ai_budget_usd": "0.00"}


def test_zone_values_are_exactly_local_and_any():
    assert AI_ZONES == ("local", "any")


@pytest.mark.parametrize("zone", ["local", "any"])
def test_zone_is_accepted_and_kept_verbatim(zone):
    assert normalize_run_policy({**BASE, "ai_zone": zone}) == {
        "ai": 1, "ai_budget_usd": "1.00", "cap_units": 1_000_000,
        "currency": "USD", "ai_zone": zone}


@pytest.mark.parametrize("zone", ["cloud", "Local", "LOCAL", "", "on-prem", "any ",
                                  None, True, False, 0, 1, ["local"], {"zone": "local"}])
def test_unknown_zone_is_refused_rather_than_coerced(zone):
    with pytest.raises(BudgetError, match="ai_zone"):
        normalize_run_policy({**BASE, "ai_zone": zone})


def test_absent_zone_round_trips_byte_identically():
    """An accepted pre-field snapshot must normalize to what it normalized to before.

    Asserted as the canonical encoding `persist_run_policy` actually stores and compares,
    not just as a dict, because that comparison is what would fail in production.
    """
    result = normalize_run_policy(dict(BASE))
    assert "ai_zone" not in result
    assert json.dumps(result, sort_keys=True, separators=(",", ":")) == (
        '{"ai":1,"ai_budget_usd":"1.00","cap_units":1000000,"currency":"USD"}')
    assert normalize_run_policy(dict(BASE)) == result
    assert normalize_run_policy(None) is None


def test_zone_without_a_budget_is_refused_not_dropped():
    """Unmanaged snapshots normalize to None, so a zone there would vanish silently."""
    with pytest.raises(BudgetError, match="processing zone"):
        normalize_run_policy({"ai": 1, "ai_zone": "local"})


def test_standing_approval_on_a_local_run_needs_no_positive_cap():
    assert normalize_run_policy({**ZERO, "ai_zone": "local", "auto_approve_ai": True}) == {
        "ai": 1, "ai_budget_usd": "0.00", "cap_units": 0, "currency": "USD",
        "ai_zone": "local", "auto_approve_ai": True}


@pytest.mark.parametrize("zone", [{"ai_zone": "any"}, {}])
def test_standing_approval_with_zero_cap_never_authorizes_cloud_spending(zone):
    policy = normalize_run_policy({**ZERO, **zone, "auto_approve_ai": True})
    assert policy['auto_approve_ai'] is True
    context = RunContext(None, "owner", "scan", "run", policy)
    assert context.enabled is False
    assert context.local_drafting is False


@pytest.mark.parametrize("ai", [0, 2, 3])
@pytest.mark.parametrize("amount", ["0.00", "1.00"])
@pytest.mark.parametrize("zone", [{"ai_zone": "local"}, {"ai_zone": "any"}, {}])
def test_standing_approval_still_requires_ai_level_one_in_every_zone(ai, amount, zone):
    with pytest.raises(BudgetError, match="requires AI enabled"):
        normalize_run_policy({"ai": ai, "ai_budget_usd": amount, **zone,
                              "auto_approve_ai": True})


def test_standing_approval_off_is_unaffected_by_the_relaxation():
    assert normalize_run_policy({**ZERO, "ai_zone": "local", "auto_approve_ai": False}) == {
        "ai": 1, "ai_budget_usd": "0.00", "cap_units": 0, "currency": "USD",
        "ai_zone": "local", "auto_approve_ai": False}


def test_a_zero_cap_local_run_can_still_buy_nothing():
    """The relaxation admits the policy; it does not admit an unmetered request.

    Every managed generation seam (llm_waterfall_provider.managed_text_generate,
    managed_generate_attempts, managed_text_ready, ai.run_verified_remediation) refuses
    on `not ctx.enabled`, and in a managed run the legacy unbudgeted paths defer instead
    of falling back to Ollama. So `enabled` is the whole cloud-exposure question here.
    """
    policy = normalize_run_policy({**ZERO, "ai_zone": "local", "auto_approve_ai": True})
    context = RunContext(None, "owner", "scan", "run", policy)
    assert context.enabled is False
    assert normalize_run_policy({**BASE, "ai_zone": "any"})["cap_units"] > 0


def test_threshold_policy_still_requires_a_positive_cap_on_a_local_run():
    """Explicitly NOT relaxed: only the standing-approval gate moved."""
    with pytest.raises(BudgetError, match="positive run budget"):
        normalize_run_policy({**ZERO, "ai_zone": "local",
                              "threshold_policy": {"minimum_reliability": "0.9"}})


# ── Dispatch: what `local` now actually permits ───────────────────────────────────────────────
# Until this change `ai_zone` was a declaration nothing in the dispatch path read, so a
# zero-cap local run was accepted and then generated nothing at all — the plan offered "keep
# AI on our own infrastructure" and silently produced no drafts. The fix is deliberately TWO
# permissions rather than one relaxed gate: `enabled` still means "may spend on the cloud
# waterfall" and still demands a positive cap, and a separate `local_drafting` means "may draft
# on the keyless floor". Making `enabled` itself true for a zero-cap local run would have opened
# every cloud seam that reads it to a run with no budget to answer for it.

def _context(**policy):
    return RunContext(None, "owner", "scan", "run", normalize_run_policy({**ZERO, **policy}))


def test_a_zero_cap_local_run_may_draft_locally_but_may_not_spend_on_the_cloud():
    context = _context(ai_zone="local")
    assert context.local_drafting is True
    assert context.enabled is False          # the cloud gate is untouched


def test_a_cloud_capable_run_never_gets_the_local_permission():
    assert _context(ai_zone="any").local_drafting is False


def test_an_absent_zone_does_not_acquire_the_local_permission():
    """Absent is the pre-field meaning of an already-stored snapshot.

    Reading it as consent to a different dispatch path would change what an accepted run
    agreed to, retroactively, for every run stored before the field existed.
    """
    assert _context().local_drafting is False


def test_ai_off_grants_neither_permission():
    context = RunContext(None, "owner", "scan", "run",
                         normalize_run_policy({"ai": 0, "ai_budget_usd": "0.00"}))
    assert context.local_drafting is False and context.enabled is False


def test_a_funded_local_run_still_denies_cloud():
    context = RunContext(None, "owner", "scan", "run",
                         normalize_run_policy({**BASE, "ai_zone": "local"}))
    assert context.local_drafting is True and context.enabled is False
