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


def fleet_ceiling(*, api_max, api_min, worker_max, worker_min, worker_threads,
                  api_override=None, worker_override=None, overlap=True) -> int:
    """Connections the fleet may hold at once.

    One process per replica (verified: uvicorn with no --workers). `overlap` adds the OUTGOING
    revision at its MINIMUM replicas — a rolling deploy runs both revisions, and the incoming one
    is what scales to max under load, so min-of-old plus max-of-new is the realistic worst case
    rather than a doubling of everything.
    """
    api = pool_for(0, api_override)
    wrk = pool_for(worker_threads, worker_override)
    total = api_max * api + worker_max * wrk
    if overlap:
        total += api_min * api + worker_min * wrk
    return total


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
