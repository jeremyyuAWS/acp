"""The fleet-wide Postgres connection budget, as arithmetic that runs.

PRD "Automatic Worker Provisioning" §4.C:

    API connections + worker connections + deployment overlap + operational reserve
        <= usable database capacity

That inequality was written down twice and never evaluated, which is how the pool fix in #1045 —
correct about the incident it targeted — took production's ceiling from 230 to 328 against a
150-connection server without anyone noticing. A budget nobody can run is a budget nobody checks.

So it lives here as a function. `fleet_ceiling` derives every pool from the SAME db_max_conn the
containers use, rather than restating the formula, so a change to the formula moves these numbers
too instead of silently invalidating them.

WHAT IS VERIFIED HERE vs WHAT IS CARRIED:

  Verified in this repo at a50d067c:
    * the formula, max(2, ACP_WORKERS + 16)                        api/store.py
    * ACP_DB_MAX_CONN is set by NO deploy script, so no override is in force anywhere
    * ONE process per replica — `uvicorn app:app` carries no --workers
      (deploy/public/Dockerfile) and the worker tier is one process of N threads
    * deploy.sh's CREATE-time limits: API 1-1, worker 1-3, ACP_WORKER_COUNT default 2

  Carried from the 2026-08-30 Azure read, NOT re-verified here (this container has no Azure
  access, and reading live configuration is a separate authorised step):
    * production   API 1-3, worker 3-10, ACP_WORKERS=12, max_connections=150
    * staging      API 1-1, worker 1-3,  ACP_WORKERS=2,  max_connections=50

  Note the two disagree: deploy.sh only passes replica flags on CREATE, never on UPDATE, so live
  limits persist from whatever was set out of band. The script is not the source of truth for a
  running deployment, and these numbers must be re-read from Azure before anything is applied.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from store import db_max_conn  # noqa: E402


def pool_for(workers: int, override: int | None = None) -> int:
    """One process's pool ceiling, from the container's own function."""
    env = {"ACP_WORKERS": str(workers)}
    if override is not None:
        env["ACP_DB_MAX_CONN"] = str(override)
    return db_max_conn(env)


@dataclass(frozen=True)
class Tier:
    """One container app: its replica range, its thread count, and any pool override.

    A TIER, not "the API and the worker". The two-tier shape this file was written around no
    longer describes production, which runs acp-app plus THREE role-restricted worker apps
    (acp-discovery / acp-assess / acp-remediate, per docs/worker-split.md and
    deploy/public/rightsize-production.sh). The old signature could not express that at all, so
    the budget it computed was for a topology that had been split underneath it — which is the
    same way the 3-10 replica model went stale.
    """

    name: str
    max_replicas: int
    min_replicas: int
    threads: int                      # ACP_WORKERS on that app; 0 for the API tier
    override: int | None = None       # ACP_DB_MAX_CONN, if one is set

    @property
    def pool(self) -> int:
        return pool_for(self.threads, self.override)

    @property
    def ceiling(self) -> int:
        return self.max_replicas * self.pool


def fleet_ceiling_tiers(tiers: "list[Tier]", *, overlap: bool = True) -> int:
    """Connections the fleet may hold at once, over any number of tiers.

    One process per replica (verified: uvicorn with no --workers). `overlap` adds the OUTGOING
    revision at its MINIMUM replicas — a rolling deploy runs both revisions, and the incoming one
    is what scales to max under load, so min-of-old plus max-of-new is the realistic worst case
    rather than a doubling of everything.
    """
    total = sum(t.ceiling for t in tiers)
    if overlap:
        total += sum(t.min_replicas * t.pool for t in tiers)
    return total


def fleet_ceiling(*, api_max, api_min, worker_max, worker_min, worker_threads,
                  api_override=None, worker_override=None, overlap=True) -> int:
    """The two-tier form, kept because the proposal below is stated in it.

    Delegates to `fleet_ceiling_tiers` rather than repeating the arithmetic, so the two cannot
    disagree; `test_the_two_tier_form_is_the_general_form` holds that.
    """
    return fleet_ceiling_tiers([
        Tier("api", api_max, api_min, 0, api_override),
        Tier("worker", worker_max, worker_min, worker_threads, worker_override),
    ], overlap=overlap)


# Operational reserve: schema migrations, scripts/monitor.py, an admin psql session, Azure
# diagnostics. Not a guess dressed as a measurement — a stated allowance, to be revised when the
# real count is known.
RESERVE_PROD = 15
RESERVE_STAGING = 8

PROD_LIMIT = 150
STAGING_LIMIT = 50

# Live shape as read on 2026-08-30 (carried, see module docstring).
PROD_TODAY = dict(api_max=3, api_min=1, worker_max=10, worker_min=3, worker_threads=12)
STAGING_TODAY = dict(api_max=1, api_min=1, worker_max=3, worker_min=1, worker_threads=2)


def test_production_does_not_fit_its_server_today():
    """The finding, pinned. Not a failing build — a recorded fact that must change deliberately.

    If someone brings production within budget, this test fails and points them at the proposal
    below and at docs/db-connection-budget.md, so the documentation moves with the change.
    """
    steady = fleet_ceiling(**PROD_TODAY, overlap=False)
    during_deploy = fleet_ceiling(**PROD_TODAY)
    assert steady == 328, f"the steady ceiling moved to {steady}; re-check the proposal"
    assert during_deploy == 428, f"the deploy ceiling moved to {during_deploy}"
    assert steady + RESERVE_PROD > PROD_LIMIT, (
        "production now fits its connection budget — update docs/db-connection-budget.md and "
        "this test together")


def test_staging_does_not_fit_its_server_today():
    steady = fleet_ceiling(**STAGING_TODAY, overlap=False)
    during_deploy = fleet_ceiling(**STAGING_TODAY)
    assert steady == 70, f"the steady ceiling moved to {steady}; re-check the proposal"
    assert during_deploy == 104, f"the deploy ceiling moved to {during_deploy}"
    assert steady + RESERVE_STAGING > STAGING_LIMIT


def test_no_per_process_pool_can_rescue_ten_worker_replicas():
    """Why the proposal reduces worker max-replicas rather than only shrinking pools.

    At 10 worker replicas the worker term alone dominates: even a pool of 10 per process — under
    one connection per thread, so every job thread would contend — leaves nothing for the API.
    """
    worst = fleet_ceiling(**{**PROD_TODAY, "worker_override": 10, "api_override": 10})
    assert worst + RESERVE_PROD > PROD_LIMIT, (
        "a pool small enough to fit would make this test fail — recompute the proposal")


# ── The proposal ──────────────────────────────────────────────────────────────────────────────
# Concrete, role-specific, and derived from the numbers above rather than chosen to look tidy.
# NOT APPLIED ANYWHERE: these are values for the platform owner to approve and set, after staging
# validation. Nothing in this repo reads them.
PROPOSED_PROD = dict(api_max=3, api_min=1, worker_max=4, worker_min=3, worker_threads=12,
                     api_override=12, worker_override=12)
# Staging is the tight one, and that is a finding rather than a tuning choice. Its
# max_connections is 50 — the Postgres system default, never overridden the way production's was
# raised to 150 — and its own observed 24h peak is 27. Once a deploy overlap and any reserve are
# allowed for, the arithmetic leaves a STEADY ceiling of about 27: the environment is already
# using essentially all of the server it has. These values fit, exactly, and the real
# recommendation in docs/db-connection-budget.md is to raise staging's max_connections so it can
# actually rehearse production's budget rather than being the first thing to run out.
PROPOSED_STAGING = dict(api_max=1, api_min=1, worker_max=3, worker_min=1, worker_threads=2,
                        api_override=9, worker_override=6)


def test_the_proposed_production_budget_fits_with_its_reserve():
    ceiling = fleet_ceiling(**PROPOSED_PROD)
    assert ceiling + RESERVE_PROD <= PROD_LIMIT, (
        f"proposed production ceiling {ceiling} + reserve {RESERVE_PROD} exceeds {PROD_LIMIT}")
    # And it must still be worth having: comfortably above the observed 24h peak of 74.
    assert ceiling >= 100, "the proposal has been tightened below the observed real peak"


def test_the_proposed_staging_budget_fits_with_its_reserve():
    ceiling = fleet_ceiling(**PROPOSED_STAGING)
    assert ceiling + RESERVE_STAGING <= STAGING_LIMIT, (
        f"proposed staging ceiling {ceiling} + reserve {RESERVE_STAGING} exceeds {STAGING_LIMIT}")
    # The steady ceiling — not the deploy one — is what has to cover real use, and staging's own
    # observed 24h peak was 27. Anything less would be proposing a budget the environment has
    # already exceeded in practice.
    steady = fleet_ceiling(**PROPOSED_STAGING, overlap=False)
    assert steady >= 27, (
        f"proposed staging steady ceiling {steady} is below its observed peak of 27")


def test_the_proposal_is_expressed_as_an_explicit_per_role_override():
    """H-01 asked for role-specific budgets. One formula for every role is what took the worker
    tier from 20 to 28 as a side effect of fixing the API, so the proposal sets both explicitly
    rather than relying on ACP_WORKERS to imply them."""
    assert pool_for(0, PROPOSED_PROD["api_override"]) == 12
    assert pool_for(12, PROPOSED_PROD["worker_override"]) == 12
    # Without an override the worker tier's pool is driven by its thread count, which is the
    # coupling the override exists to break.
    assert pool_for(12) == 28


def test_an_override_below_the_floor_is_still_clamped():
    """A budget must not be settable to something that cannot serve a request at all."""
    assert pool_for(12, 0) == 2
    assert pool_for(12, 1) == 2


# ── The deployed shape is THREE worker tiers, not one ─────────────────────────────────────────
#
# Everything above models one worker tier at 3-10 replicas. Production does not have one. It runs
# acp-app plus three role-restricted worker apps, and deploy/public/rightsize-production.sh is the
# reviewed capacity baseline that sets them:
#
#     acp-app        1.0 CPU  2Gi  replicas 1-3
#     acp-discovery  1.0 CPU  2Gi  replicas 1-2
#     acp-assess     2.0 CPU  4Gi  replicas 5-5
#     acp-remediate  2.0 CPU  4Gi  replicas 5-5
#
# So "cut worker max-replicas from 10 to 4" has no tier to act on: nothing in the repo's own
# baseline is at 10. The tests below recompute against the shape that is actually configured.
#
# WHAT IS CARRIED AND WHAT IS NOT. The replica ranges are VERIFIED in this repo
# (rightsize-production.sh). ACP_WORKERS on the three worker apps is NOT: deploy/public/
# redeploy.sh sets it on none of them, so each inherits whatever was set out of band, and
# api/worker_main.py forces 12 when it is unset. Rather than pick one and present it as fact,
# these tests assert over BOTH plausible values — 2 (deploy.sh's ACP_WORKER_COUNT default) and 12
# (the 2026-08-30 Azure read) — and assert only the conclusion that holds either way.

# Verified: deploy/public/rightsize-production.sh.
RIGHTSIZE_REPLICAS = {
    "acp-app": (1, 3),
    "acp-discovery": (1, 2),
    "acp-assess": (5, 5),
    "acp-remediate": (5, 5),
}
PLAUSIBLE_WORKER_THREADS = (2, 12)


def deployed_tiers(worker_threads: int, *, worker_override=None, api_override=None,
                   assess_range=None, remediate_range=None) -> list[Tier]:
    """The four production container apps, with the worker replica ranges optionally overridden."""
    ranges = dict(RIGHTSIZE_REPLICAS)
    if assess_range:
        ranges["acp-assess"] = assess_range
    if remediate_range:
        ranges["acp-remediate"] = remediate_range
    tiers = [Tier("acp-app", ranges["acp-app"][1], ranges["acp-app"][0], 0, api_override)]
    for name in ("acp-discovery", "acp-assess", "acp-remediate"):
        lo, hi = ranges[name]
        tiers.append(Tier(name, hi, lo, worker_threads, worker_override))
    return tiers


@pytest.mark.parametrize("threads", PLAUSIBLE_WORKER_THREADS)
def test_the_deployed_three_tier_shape_exceeds_the_server_whatever_acp_workers_is(threads):
    """The corrected finding. 328 was for a topology production no longer has.

    Asserted over both plausible thread counts because the real one is not knowable from this
    repository, and the conclusion does not depend on it.
    """
    steady = fleet_ceiling_tiers(deployed_tiers(threads), overlap=False)
    assert steady + RESERVE_PROD > PROD_LIMIT, (
        f"at ACP_WORKERS={threads} the deployed four-app shape now fits {PROD_LIMIT} "
        f"(steady {steady}) — update docs/db-connection-budget.md, which still says it does not")


def test_the_split_raised_the_ceiling_above_the_single_worker_tier_model():
    """Splitting one worker tier into three multiplied the term that already dominated.

    Pinned because docs/db-connection-budget.md's headline number (328) is now an UNDERSTATEMENT
    of the shape it was describing, and an understated budget is the kind that gets accepted.
    """
    single_tier = fleet_ceiling(**PROD_TODAY, overlap=False)
    three_tier = fleet_ceiling_tiers(deployed_tiers(12), overlap=False)
    assert single_tier == 328
    assert three_tier == 384
    assert three_tier > single_tier


@pytest.mark.parametrize("threads", PLAUSIBLE_WORKER_THREADS)
def test_cutting_assess_and_remediate_to_four_does_not_reach_the_budget(threads):
    """Why "cut worker max-replicas to 4" is not sufficient on its own.

    It is the doc's proposal carried onto the deployed shape, and it does not arrive: the cut pays
    the throughput cost (rightsize-production.sh keeps five replicas warm deliberately, for the
    batch stages' performance baseline) without buying the safety margin it was supposed to buy.
    """
    cut = deployed_tiers(threads, assess_range=(1, 4), remediate_range=(1, 4))
    steady = fleet_ceiling_tiers(cut, overlap=False)
    assert steady + RESERVE_PROD > PROD_LIMIT, (
        f"cutting to 4 now fits at ACP_WORKERS={threads} (steady {steady}) — recompute the "
        f"proposal in docs/db-connection-budget.md")


def test_cutting_to_four_does_not_fit_even_with_the_proposed_pool_override():
    """The proposal's OTHER half does not rescue it either, on the three-tier shape.

    ACP_DB_MAX_CONN=12 on every app, with assess and remediate at max 4, still lands over the
    server. This is the arithmetic behind "verify the live configuration before tuning": the
    published proposal was computed for two tiers and does not transfer.
    """
    cut = deployed_tiers(12, worker_override=12, api_override=12,
                         assess_range=(1, 4), remediate_range=(1, 4))
    steady = fleet_ceiling_tiers(cut, overlap=False)
    assert steady == 156
    assert steady + RESERVE_PROD > PROD_LIMIT


def test_the_two_tier_form_is_the_general_form():
    """Bite check for the refactor: the old signature must not have acquired its own arithmetic."""
    kwargs = dict(api_max=3, api_min=1, worker_max=10, worker_min=3, worker_threads=12)
    explicit = fleet_ceiling_tiers([
        Tier("api", 3, 1, 0), Tier("worker", 10, 3, 12),
    ])
    assert fleet_ceiling(**kwargs) == explicit
    assert fleet_ceiling(**kwargs, overlap=False) == fleet_ceiling_tiers(
        [Tier("api", 3, 1, 0), Tier("worker", 10, 3, 12)], overlap=False)


def test_the_replica_ranges_here_match_the_rightsize_script():
    """These numbers are only worth asserting on if they still describe the reviewed baseline."""
    import re
    script = (Path(__file__).resolve().parent.parent
              / "deploy" / "public" / "rightsize-production.sh").read_text()
    found = {
        m.group(1): (int(m.group(2)), int(m.group(3)))
        for m in re.finditer(r"^update_app\s+(\S+)\s+\S+\s+\S+\s+(\d+)\s+(\d+)", script, re.M)
    }
    for name, expected in RIGHTSIZE_REPLICAS.items():
        assert found.get(name) == expected, (
            f"{name} is {found.get(name)} in rightsize-production.sh but {expected} here — the "
            f"baseline moved, so every number in this section needs recomputing")
