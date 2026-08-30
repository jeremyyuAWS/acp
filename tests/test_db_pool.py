"""The Postgres pool must survive every worker being busy.

Live symptom: `psycopg2.pool.PoolError: connection pool exhausted` from /hitl/auto-queue.
The pool was a fixed 5 while ACP_WORKERS was 4 — four worker threads plus a dashboard poll
(which hits /jobs, /hitl/queue and /scans/{id}/remediation-status together) is already six.
The reviewer saw "HITL queue: no items" while items were waiting to be queued.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store  # noqa: E402


# ── sizing ──

def test_pool_is_larger_than_the_worker_count():
    # The bug in one assertion: 4 workers must never share a 5-connection pool with the API.
    assert store.db_max_conn({"ACP_WORKERS": "4"}) > 4 + 1


def test_pool_scales_with_workers():
    assert store.db_max_conn({"ACP_WORKERS": "16"}) > store.db_max_conn({"ACP_WORKERS": "4"})


def test_pool_leaves_headroom_for_concurrent_http_handlers():
    workers = 4
    assert store.db_max_conn({"ACP_WORKERS": str(workers)}) - workers >= 8


def test_explicit_override_wins():
    assert store.db_max_conn({"ACP_DB_MAX_CONN": "30", "ACP_WORKERS": "4"}) == 30


def test_bad_env_falls_back_instead_of_crashing_at_import():
    assert store.db_max_conn({"ACP_WORKERS": "not-a-number"}) >= 2
    assert store.db_max_conn({}) >= 2


def test_pool_stays_well_under_small_sku_max_connections():
    # Azure Postgres small SKUs cap ~50. A replica must not try to hog them all.
    assert store.db_max_conn({"ACP_WORKERS": "16"}) < 50


# ── the 2026-08-30 regression: ACP_WORKERS="0" must not collapse the API headroom ──

def test_api_tier_with_zero_workers_gets_full_headroom_not_a_worker_floor():
    """The actual production bug. ACP_WORKERS="0" is a non-empty string, so it survives the
    `or 4` fallback below (`e.get("ACP_WORKERS") or 4` — "0" is truthy) and workers=int("0")==0
    reaches the pool-size arithmetic as a real 0, not the unset-fallback of 4.

    The OLD formula routed that through `max(2, workers) + _API_HEADROOM_CONN`:
    `max(2, 0) + 8 == 10` — the API replica's own pool floored at 10 connections while serving
    real, observed concurrent HTTP traffic (inventory pagination, /jobs polling, queue-estimate,
    HITL, decisions) that routinely exceeded that. The fix decouples the headroom term from
    `workers` entirely, so a serve-only replica (ACP_WORKERS=0 by design, split topology / #113)
    gets the FULL headroom, not a worker-count-derived floor."""
    assert store.db_max_conn({"ACP_WORKERS": "0"}) == store._API_HEADROOM_CONN
    # However _API_HEADROOM_CONN gets tuned in the future, it must stay comfortably above the
    # incident's own number ("comfortably more than 10 concurrent DB-touching HTTP handlers").
    assert store.db_max_conn({"ACP_WORKERS": "0"}) > 10


def test_negative_or_garbage_workers_cannot_starve_the_headroom_term():
    # A malformed or negative ACP_WORKERS must not propagate into a negative pool size, and
    # must not fall through to the unset-default(4) path either — it is a real, if bad, value.
    assert store.db_max_conn({"ACP_WORKERS": "-5"}) == store._API_HEADROOM_CONN


def test_worst_case_deployed_fleet_stays_under_the_confirmed_postgres_ceiling():
    """The arithmetic behind the PR's chosen _API_HEADROOM_CONN, expressed as a fixture instead
    of just a comment. Real, confirmed constraints (2026-08-30 incident + deploy/public/deploy.sh):
      - Postgres max_connections == 150 (confirmed live).
      - The API Container App is --min-replicas 1 --max-replicas 1 — ALWAYS exactly one replica.
      - The worker Container App is --min-replicas 1 --max-replicas 3, at ACP_WORKER_COUNT (default
        2, deploy.sh's `WK_N="${ACP_WORKER_COUNT:-2}"`) workers per replica by default.
    """
    api_pool = store.db_max_conn({"ACP_WORKERS": "0"})
    worker_pool_at_default = store.db_max_conn({"ACP_WORKERS": "2"})   # deploy.sh's WK_N default
    fleet_at_default = 1 * api_pool + 3 * worker_pool_at_default
    assert fleet_at_default < 150

    # core.py's own live-scaling safety cap on ACP_WORKERS is 16 (_MAX_WORKERS) — an operator
    # pushing the worker tier that hard, at its max replica count, is the actual edge this
    # headroom needs to stay honest about rather than silently assume away.
    worker_pool_at_cap = store.db_max_conn({"ACP_WORKERS": "16"})
    fleet_at_worker_cap = 1 * api_pool + 3 * worker_pool_at_cap
    assert fleet_at_worker_cap < 150


# ── getconn waits instead of failing instantly ──

class _FakePoolError(Exception):
    pass


class _FakePool:
    """Mimics ThreadedConnectionPool: raises immediately while exhausted, never blocks."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def getconn(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise _FakePoolError("connection pool exhausted")
        return "conn"


@pytest.fixture()
def pg(monkeypatch):
    # psycopg2 isn't installed in the local (SQLite) test env, and _getconn imports it at
    # call time. Stand in a module exposing the one symbol it catches on.
    import types
    fake_pool = types.ModuleType("psycopg2.pool")
    fake_pool.PoolError = _FakePoolError
    fake_pg = types.ModuleType("psycopg2")
    fake_pg.pool = fake_pool
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    monkeypatch.setitem(sys.modules, "psycopg2.pool", fake_pool)
    return store._PgAdapter.__new__(store._PgAdapter)


def test_getconn_retries_through_a_transient_burst(pg, monkeypatch):
    pool = _FakePool(fail_times=3)
    monkeypatch.setattr(pg, "_get_pool", lambda: pool)
    assert pg._getconn(timeout=2.0) == "conn"
    assert pool.calls == 4          # it waited rather than surfacing the first PoolError


def test_getconn_still_raises_when_the_pool_stays_empty(pg, monkeypatch):
    # A pool empty for seconds is a real problem — it must not be swallowed forever.
    pool = _FakePool(fail_times=10**6)
    monkeypatch.setattr(pg, "_get_pool", lambda: pool)
    started = time.monotonic()
    with pytest.raises(_FakePoolError):
        pg._getconn(timeout=0.2)
    assert time.monotonic() - started >= 0.2


# ── app-level: PoolError must surface as a clean 503, not a bare 500 ──

def test_pool_exhaustion_surfaces_as_a_clean_503_not_a_bare_500(monkeypatch):
    """api/app.py registers a FastAPI exception handler for psycopg2.pool.PoolError — the exact
    exception _getconn() raises once its retry window elapses (see the two tests just above).
    Before that handler existed, this propagated as FastAPI's generic, undifferentiated 500 —
    exactly what POST /discovery/preflight and POST /scans both did during the 2026-08-30
    incident, with no distinguishable body a frontend fix could branch on.

    Uses the REAL psycopg2.pool.PoolError (psycopg2 is genuinely installed in this sandbox —
    api/requirements.txt pins psycopg2-binary) rather than the `pg` fixture's sys.modules
    stand-in above: app.py imports psycopg2.pool once, at module import time, and registers its
    handler against whatever class it saw then — for a module cached once per test session
    that's the real one, not a fixture-scoped fake swapped in mid-session."""
    import psycopg2.pool
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)

    class _ExhaustedStore:
        # /jobs' very first store call — raising here means nothing downstream in the route
        # runs, so this reproduces "pool exhausted before any query" precisely.
        def worker_tier_status(self):
            raise psycopg2.pool.PoolError("connection pool exhausted")

    monkeypatch.setattr(core, "store", _ExhaustedStore())
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/jobs")

    assert r.status_code == 503
    assert r.headers.get("retry-after") == "5"
    body = r.json()
    assert body["detail"] == "database_busy"
    assert "capacity" in body["message"].lower()
    assert "no changes were made" in body["message"].lower()
