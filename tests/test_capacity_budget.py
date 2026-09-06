"""The fleet capacity inequality, and what it says about the Scheduling PRD's capacity table.

`api/capacity_budget.py` is the same arithmetic `tests/test_db_connection_budget.py` has computed
since #1045's aftermath, moved into importable code because the Scheduling feature needs it at
request time: `POST /control/capacity-schedule/validate` has to refuse a schedule before it is
saved, and a model only a test can call cannot do that.

TWO THINGS THIS FILE HOLDS.

First, that the move did not change the answer. The tiers here are PARSED from
deploy/public/rightsize-production.sh rather than restated, so the reviewed baseline moving (as
it does — discovery's range was under review on 2026-09-06) flows through instead of turning
into a stale constant, and the module's figures are compared against the existing test module's
on the same shape.

Second, the finding the Scheduling PRD needs before Phase 3 writes anything: ITS PROPOSED
SERVICE-CAPACITY TABLE DOES NOT FIT THE SERVER, and it fails in the one mode nobody validates.
The binding term is the deployment overlap, overlap is driven by the FLOORS, and the PRD raises
floors during business hours — so the shape is affordable at 2am and over budget at 10am, which
is when someone deploys.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from capacity_budget import Tier, connections, evaluate, vcpu, worst_case_tiers  # noqa: E402

# Both from deploy/public/rightsize-production.sh, and both stated allowances rather than
# measurements — the same two constants tests/test_db_connection_budget.py carries.
PROD_LIMIT = 150
RESERVE_PROD = 15
WORKER_DB_POOL = 2

# ACP_WORKERS is not set per app by any deploy script, so the pool is pinned by ACP_DB_MAX_CONN
# instead and the thread count does not reach the arithmetic. 2 is the value the script sets.
WORKER_THREADS = 2


def _rightsize_ranges() -> dict[str, tuple[int, int]]:
    """The reviewed baseline's replica ranges, read from the script that applies them."""
    script = (ROOT / "deploy/public/rightsize-production.sh").read_text()
    return {
        m.group(1): (int(m.group(2)), int(m.group(3)))
        for m in re.finditer(r"^update_app\s+(\S+)\s+(?:\S+)\s+(?:\S+)\s+(\d+)\s+(\d+)",
                             script, re.M)
    }


# CPU per replica, also from the script. Named here because `update_app`'s positional arguments
# are cpu/memory/min/max and parsing four of them into one regex reads worse than two passes.
def _rightsize_cpu() -> dict[str, float]:
    script = (ROOT / "deploy/public/rightsize-production.sh").read_text()
    return {
        m.group(1): float(m.group(2))
        for m in re.finditer(r"^update_app\s+(\S+)\s+([\d.]+)\s+\S+\s+\d+\s+\d+", script, re.M)
    }


def deployed_tiers(**overrides) -> list[Tier]:
    """The four production container apps as the script configures them.

    `overrides` replaces one app's (min, max) — used below to price a proposal without
    restating the rest of the fleet.
    """
    ranges = {**_rightsize_ranges(), **overrides}
    cpu = _rightsize_cpu()
    tiers = []
    for name in ("acp-app", "acp-discovery", "acp-assess", "acp-remediate"):
        lo, hi = ranges[name]
        # acp-app runs ACP_WORKERS=0 by design (ADR 0013) and takes no pool override; the three
        # worker apps take ACP_DB_MAX_CONN=2 from the script's `db_pool` argument.
        is_api = name == "acp-app"
        tiers.append(Tier(name, lo, hi,
                          threads=0 if is_api else WORKER_THREADS,
                          db_pool_override=None if is_api else WORKER_DB_POOL,
                          cpu_cores=cpu[name]))
    return tiers


# ── the move must not have changed the answer ────────────────────────────────────────────────

def test_the_module_agrees_with_the_test_only_model_it_was_moved_out_of():
    """Bite check for the extraction: two implementations of one inequality that disagree is
    worse than one that only a test could call."""
    from test_db_connection_budget import Tier as OldTier, fleet_ceiling_tiers

    tiers = deployed_tiers()
    old = [OldTier(t.name, t.max_replicas, t.min_replicas, t.threads, t.db_pool_override)
           for t in tiers]
    assert connections(tiers, overlap=False) == fleet_ceiling_tiers(old, overlap=False)
    assert connections(tiers, overlap=True) == fleet_ceiling_tiers(old, overlap=True)


def test_the_reviewed_baseline_fits_its_server():
    result = evaluate(deployed_tiers(), server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert not result["blocked"], result["findings"]
    assert result["connection_headroom"] >= 0


def test_the_pools_come_from_the_containers_own_function():
    """Not a restated formula. A change to store.db_max_conn must move these numbers."""
    tiers = {t.name: t for t in deployed_tiers()}
    assert tiers["acp-remediate"].pool == 2, "the ACP_DB_MAX_CONN override stopped being applied"
    # 0 worker threads + _API_HEADROOM_CONN. Asserted through the function, not against 16, so
    # the headroom constant remains free to move without this test claiming it did not.
    from store import db_max_conn
    assert tiers["acp-app"].pool == db_max_conn({"ACP_WORKERS": "0"})


# ── the overlap term is driven by the floors, which is what Scheduling changes ────────────────

def test_raising_a_floor_raises_the_worst_case_even_though_the_ceiling_did_not_move():
    """The whole reason a capacity SCHEDULE needs validating against every mode.

    A schedule does not touch maximums; it moves floors. Azure runs the outgoing and incoming
    revisions together during a rollout, so the floor is a term in the fleet's worst case — and
    a business-hours floor is a worst case that only exists during the hours people deploy in.
    """
    low = deployed_tiers(**{"acp-remediate": (1, 10)})
    high = deployed_tiers(**{"acp-remediate": (5, 10)})
    assert connections(low, overlap=False) == connections(high, overlap=False), (
        "the ceilings are identical, so the steady figure must be too")
    assert connections(high) > connections(low), (
        "raising a floor did not raise the deploy-overlap figure — the overlap term is gone")


def test_the_worst_mode_is_taken_across_every_mode_a_schedule_can_be_in():
    tiers = deployed_tiers(**{"acp-assess": (1, 10), "acp-remediate": (1, 10)})
    worst = {t.name: t for t in worst_case_tiers(tiers, {
        "business_hours": {"acp-assess": 5, "acp-remediate": 5},
        "off_hours": {"acp-assess": 1, "acp-remediate": 1},
    })}
    assert worst["acp-assess"].min_replicas == 5
    assert worst["acp-remediate"].min_replicas == 5
    # A tier no mode names keeps what it had, so a partial schedule is expressible.
    assert worst["acp-app"].min_replicas == _rightsize_ranges()["acp-app"][0]


# ── the PRD's own capacity table, priced ─────────────────────────────────────────────────────
#
# docs/prd-capacity-scheduling.md §5.3, verbatim: web 2/1/3, discovery 2/1/4, assess 5/1/10,
# remediate 5/1/10 (business floor / off-hours floor / maximum). GPU is not a Postgres client and
# does not appear in this budget.
PRD_MAXIMUMS = {"acp-app": 3, "acp-discovery": 4, "acp-assess": 10, "acp-remediate": 10}
PRD_BUSINESS_FLOORS = {"acp-app": 2, "acp-discovery": 2, "acp-assess": 5, "acp-remediate": 5}
PRD_OFF_HOURS_FLOORS = {"acp-app": 1, "acp-discovery": 1, "acp-assess": 1, "acp-remediate": 1}


def _prd_tiers() -> list[Tier]:
    ranges = {name: (PRD_OFF_HOURS_FLOORS[name], PRD_MAXIMUMS[name]) for name in PRD_MAXIMUMS}
    return deployed_tiers(**ranges)


def test_the_prd_capacity_table_fits_at_night_and_that_is_the_trap():
    """Validated in off-hours mode, the PRD's table passes. This is the reading that would let
    it be saved, and it is why validation must not use the mode it happens to be in."""
    result = evaluate(_prd_tiers(), server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert not result["blocked"], result["findings"]


def test_the_prd_capacity_table_does_not_fit_during_business_hours():
    """THE FINDING. Same table, same server, evaluated against the mode the PRD itself specifies
    for weekday daytime — and a deploy landing in that window is over the connection budget.

    A failing assertion here would mean the shape became affordable, which is a good thing that
    must move docs/prd-capacity-scheduling.md with it rather than pass silently.
    """
    worst = worst_case_tiers(_prd_tiers(), {
        "business_hours": PRD_BUSINESS_FLOORS,
        "off_hours": PRD_OFF_HOURS_FLOORS,
    })
    result = evaluate(worst, server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert result["blocked"], (
        "the PRD's capacity table now fits its server — update docs/prd-capacity-scheduling.md "
        "and this test together")
    over = [f for f in result["findings"] if f["code"] == "over_connection_budget"]
    assert over, result["findings"]
    assert result["connection_headroom"] < 0


def test_a_scaler_on_assess_is_inert_until_its_ceiling_is_raised():
    """Phase 1 of the PRD asks for an Assess queue scaler. The tier is pinned at 5-5, so a rule
    attached to it can compute any replica count it likes and Azure cannot act on it — which is
    why deploy/public/rightsize-production.sh generates the rule but guards applying it."""
    floor, ceiling = _rightsize_ranges()["acp-assess"]
    assert ceiling == floor, (
        "acp-assess is no longer pinned — rightsize-production.sh should now be applying the "
        "assess-queue rule, and this test should assert that instead")
    result = evaluate(deployed_tiers(), server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    pinned = [f for f in result["findings"]
              if f["code"] == "ceiling_equals_floor" and "acp-assess" in f["detail"]]
    assert pinned, result["findings"]


def test_the_budget_says_exactly_how_much_assess_ceiling_it_affords():
    """What raising that ceiling costs, derived rather than asserted as a target.

    The answer is not fixed and must not be written down as one: it is whatever the rest of the
    fleet has left, and the rest of the fleet is under review. On the baseline as this test
    reads it, discovery's own range is the competing claim on the same connections — a discovery
    floor of 4 costs six connections of overlap that assess cannot then have.

    So this asserts the ARITHMETIC IS SELF-CONSISTENT, which holds whatever the baseline says:
    the affordable ceiling fits and one replica past it does not. A test that pinned a number
    would go red on any baseline change and teach nothing about why.
    """
    tiers = deployed_tiers()
    pool = {t.name: t.pool for t in tiers}["acp-assess"]
    floor, ceiling = _rightsize_ranges()["acp-assess"]
    headroom = evaluate(tiers, server_max_connections=PROD_LIMIT,
                        reserve=RESERVE_PROD)["connection_headroom"]
    affordable = ceiling + headroom // pool

    fits = evaluate(deployed_tiers(**{"acp-assess": (floor, affordable)}),
                    server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert not fits["blocked"], (
        f"a ceiling of {affordable} was derived as affordable but does not fit: {fits['findings']}")

    over = evaluate(deployed_tiers(**{"acp-assess": (floor, affordable + 1)}),
                    server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert over["blocked"], (
        f"one replica past the derived ceiling of {affordable} still fits — the headroom "
        f"arithmetic and the evaluation disagree")


def test_the_prd_ceilings_and_the_prd_floors_compete_for_the_same_connections():
    """Why the PRD's table has to be decided as a whole rather than service by service.

    Assess's ceiling alone is affordable on some baselines. The floors are what spend the same
    budget — and the PRD raises four floors and four ceilings at once, which is how a table of
    individually reasonable numbers lands over the limit.
    """
    assess_only = evaluate(deployed_tiers(**{"acp-assess": (5, 10)}),
                           server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    everything = evaluate(worst_case_tiers(_prd_tiers(), {
        "business_hours": PRD_BUSINESS_FLOORS, "off_hours": PRD_OFF_HOURS_FLOORS,
    }), server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert everything["deploy_connections"] > assess_only["deploy_connections"], (
        "the PRD's full table costs no more than raising assess alone — recheck the floors")
    assert everything["blocked"]


# ── evaluate's own findings ──────────────────────────────────────────────────────────────────

def test_a_floor_above_its_ceiling_is_blocking():
    result = evaluate([Tier("acp-assess", 6, 5, 2, 2, 2.0)],
                      server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert result["blocked"]
    assert any(f["code"] == "min_exceeds_max" for f in result["findings"])


def test_a_pinned_tier_is_warned_about_but_does_not_block():
    result = evaluate([Tier("acp-assess", 5, 5, 2, 2, 2.0)],
                      server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    pinned = [f for f in result["findings"] if f["code"] == "ceiling_equals_floor"]
    assert pinned and not pinned[0]["blocking"]
    assert "inert" in pinned[0]["detail"]
    # Bite check: an unpinned tier must not produce it, or the finding says nothing.
    other = evaluate([Tier("acp-assess", 5, 10, 2, 2, 2.0)],
                     server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert not [f for f in other["findings"] if f["code"] == "ceiling_equals_floor"]


def test_an_unknown_vcpu_quota_is_reported_as_unchecked_rather_than_passed():
    """No artifact in this repository records the Container Apps environment's vCPU quota, and a
    plausible default here would be indistinguishable from a measured one to a later reader. The
    demand is still computed so an operator who reads the quota can finish the check."""
    result = evaluate(deployed_tiers(), server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD)
    assert result["vcpu_quota"] is None
    unchecked = [f for f in result["findings"] if f["code"] == "vcpu_quota_unknown"]
    assert unchecked and not unchecked[0]["blocking"]
    assert "NOT checked" in unchecked[0]["detail"]
    assert result["vcpu_demand"] == vcpu(deployed_tiers())


def test_a_fleet_over_a_supplied_vcpu_quota_is_blocked():
    tiers = deployed_tiers()
    demand = vcpu(tiers)
    result = evaluate(tiers, server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD,
                      vcpu_quota=demand - 1)
    assert result["blocked"]
    assert any(f["code"] == "over_vcpu_quota" for f in result["findings"])
    assert not evaluate(tiers, server_max_connections=PROD_LIMIT, reserve=RESERVE_PROD,
                        vcpu_quota=demand)["blocked"]
