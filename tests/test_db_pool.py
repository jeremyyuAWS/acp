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
