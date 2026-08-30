"""Regression/load test for the 2026-08-30 production incident: `psycopg2.pool.PoolError:
connection pool exhausted` from POST /discovery/preflight and POST /scans, when the API
container's own pool collapsed to 10 connections under ACP_WORKERS=0 (the old formula's
`max(2, 0) + _API_HEADROOM_CONN(8) == 10`) while serving the real concurrent read set observed
live: inventory pagination, /jobs polling, queue-estimate, HITL, and decision reads.

This does NOT re-test the sizing formula in isolation — tests/test_db_pool.py already covers
that directly. It reproduces the actual FAILURE COMBINATION: real concurrent DB-touching HTTP
handlers already occupying every connection an API replica's pool holds, then a NEW scan
submission (POST /scans?queue=true — the exact route that died in production: the request dies
before the durable job row commits, so there is no scan_id and no worker-side trace at all)
arriving on top of that load.

Two things this file can and cannot prove, stated plainly:
  - It CAN prove the sizing fix (decoupling headroom from ACP_WORKERS) is what makes a scan
    submission survive this concrete combination of real, code-driven concurrent load, using
    this repo's actual routes and store methods.
  - It CANNOT prove anything about the CPU-saturation dynamics of the real Postgres server —
    that needs a real-Postgres load test against production-shaped compute, which is out of
    scope for this PR (see the PR body). The bounded pool below is a psycopg2-shaped stand-in
    for connection-slot contention only; it says nothing about server-side query cost.

The bounded pool wraps the real SQLite test adapter in a psycopg2-shaped pool (same
getconn()/PoolError contract as psycopg2.pool.ThreadedConnectionPool) sized to whatever
`max_conn` the caller passes, and reuses _PgAdapter._getconn's actual retry/timeout code rather
than reimplementing it — the thing under test is the SIZE of the pool and the code path around
it, not a new retry loop that could have its own bugs.
"""
from __future__ import annotations

import contextlib
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store as store_mod  # noqa: E402

try:
    import psycopg2.pool  # noqa: E402  — genuinely installed in this sandbox (api/requirements.txt)
    _PSYCOPG2_AVAILABLE = True
except ImportError:  # pragma: no cover — SQLite-only dev box with no Postgres driver at all
    _PSYCOPG2_AVAILABLE = False

requires_psycopg2 = pytest.mark.skipif(
    not _PSYCOPG2_AVAILABLE,
    reason="psycopg2 not installed — this load test needs the real PoolError class app.py's "
           "exception handler is registered against",
)

OWNER = "demo"

# The OLD formula's actual production value for an API replica with ACP_WORKERS=0:
# max(2, 0) + _API_HEADROOM_CONN(8) == 10. Hardcoded here — not read off store.db_max_conn,
# which now returns the FIXED value — so this test still demonstrates the old collapse forever,
# regardless of future headroom tuning.
_OLD_API_POOL_SIZE = 10

_HOLD_S = 0.5             # how long a background reader holds its "connection" — long enough
                          # for the race below to be reliable rather than timing-dependent.
_GETCONN_TIMEOUT_S = 0.2  # short, so a starved caller fails fast instead of padding CI time.
_STARTUP_GRACE_S = 0.15   # time given to the background readers to grab their slots before the
                          # scan submission is dispatched on top of them.


class _BoundedPool:
    """Mimics psycopg2.pool.ThreadedConnectionPool's getconn(): raises the moment it is empty,
    never blocks on its own — matches the real class, which is exactly why store.py's
    _getconn() has to do its own retrying (tested directly in tests/test_db_pool.py)."""

    def __init__(self, max_conn: int):
        self._sem = threading.Semaphore(max_conn)

    def getconn(self):
        if not self._sem.acquire(blocking=False):
            raise psycopg2.pool.PoolError("connection pool exhausted")
        return object()

    def putconn(self, _conn) -> None:
        self._sem.release()


class _BoundedSQLiteAdapter(store_mod._SQLiteAdapter):
    """Real SQLite queries, gated by a bounded psycopg2-shaped pool — so concurrent callers
    actually contend for a connection the way they do against the real Postgres pool, instead of
    SQLite's normal unlimited-connections behaviour masking the bug entirely."""

    def __init__(self, path: str, max_conn: int):
        super().__init__(path)
        self._MAX_CONN = max_conn
        self._pool = _BoundedPool(max_conn)

    def _get_pool(self):
        return self._pool

    # The real retry/timeout loop — reused, not reimplemented, so this test exercises production
    # code rather than a test-only stand-in for it.
    _getconn = store_mod._PgAdapter._getconn

    @contextlib.contextmanager
    def cursor(self):
        self._getconn(timeout=_GETCONN_TIMEOUT_S)
        try:
            time.sleep(_HOLD_S)  # hold the "connection" the way a live query round trip would
            with super().cursor() as cur:
                yield cur
        finally:
            self._pool.putconn(None)


def _seed(store, sid: str, n_files: int = 700) -> None:
    store.init_scan_run(sid, "drive", n_files, "2026-08-30T09:00:00+00:00", "wcag-aa", "h",
                        owner=OWNER, status="discovered")
    items = [{"file": f"doc_{i:05d}.pdf", "path": f"/doc_{i:05d}.pdf",
             "doc_class": "text-document", "size_kb": 12, "owner": OWNER,
             "created_at": "2024-01-01"} for i in range(n_files)]
    store.add_inventory(sid, items)


def _client_for(monkeypatch, store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app, raise_server_exceptions=False)


def _background_read_calls(client, sid: str) -> list:
    """The exact concurrent read set documented from the live 2026-08-30 incident: large-estate
    inventory pagination, /jobs polling, queue-estimate, HITL, and decision reads — all real,
    DB-touching route handlers, exactly matching the old pool's own size (10) so they alone
    fully occupy it without overflowing it themselves; only the scan submission on top is new
    demand."""
    calls: list = []
    for offset in (0, 100, 200, 300):
        calls.append(lambda o=offset: client.get(f"/scans/{sid}/inventory",
                                                  params={"offset": o, "limit": 100}))
    for _ in range(3):
        calls.append(lambda: client.get("/jobs"))
    calls.append(lambda: client.get(f"/scans/{sid}/queue-estimate", params={"kind": "discover"}))
    calls.append(lambda: client.get("/hitl/queue"))
    calls.append(lambda: client.get("/decisions", params={"scan_id": sid}))
    assert len(calls) == _OLD_API_POOL_SIZE  # exactly saturates the old 10-connection pool
    return calls


def _run_under_load(monkeypatch, max_conn: int):
    """Seed a scan with a large inventory, saturate `max_conn` connections with the documented
    real read traffic, then submit a NEW scan (POST /scans?queue=true, the exact route that
    died in production) into that load. Returns (background_responses, scan_response)."""
    tmp_path = Path(tempfile.mkdtemp()) / "db-pool-load.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp_path)
    store = store_mod.Store()
    sid = "load-sid"
    _seed(store, sid)
    store._db = _BoundedSQLiteAdapter(str(tmp_path), max_conn)

    client = _client_for(monkeypatch, store)
    reads = _background_read_calls(client, sid)

    ex = ThreadPoolExecutor(max_workers=len(reads))
    futures = [ex.submit(fn) for fn in reads]
    time.sleep(_STARTUP_GRACE_S)  # let the background readers grab their slots first

    scan_response = client.post("/scans", params={"source": "local", "queue": "true"})

    bg_responses = [f.result(timeout=5) for f in as_completed(futures, timeout=5)]
    ex.shutdown(wait=True)
    return bg_responses, scan_response


@requires_psycopg2
def test_old_formula_exhausts_the_pool_but_degrades_cleanly(monkeypatch):
    """With the pool sized to the OLD formula's actual production value (10), the documented
    concurrent read load alone fully occupies it — proving the incident's own claim
    ("comfortably more than 10 concurrent DB-touching HTTP handlers") — and a scan submission
    landing on top of that is starved. Before this PR, that surfaced as a bare 500; this test
    pins that it is now the documented, clean 503 instead."""
    bg_responses, scan_response = _run_under_load(monkeypatch, _OLD_API_POOL_SIZE)

    # The background reads, sized exactly to the pool, all succeed on their own.
    for r in bg_responses:
        assert r.status_code == 200, r.text

    # The scan submission, arriving on top of an already-saturated OLD-sized pool, is starved —
    # this IS the incident, reproduced against real routes and real store code.
    assert scan_response.status_code == 503, (
        f"expected the old formula to starve this request under real concurrent load, got "
        f"{scan_response.status_code}: {scan_response.text}"
    )
    body = scan_response.json()
    assert body["detail"] == "database_busy"


@requires_psycopg2
def test_fixed_sizing_lets_a_new_scan_through_under_the_same_load(monkeypatch):
    """The actual fix, proven end to end: with the pool sized by the FIXED formula
    (store.db_max_conn({"ACP_WORKERS": "0"}) — the real value an API replica computes today),
    the identical concurrent read load no longer starves a new scan submission."""
    fixed_size = store_mod.db_max_conn({"ACP_WORKERS": "0"})
    bg_responses, scan_response = _run_under_load(monkeypatch, fixed_size)

    for r in bg_responses:
        assert r.status_code == 200, r.text

    assert scan_response.status_code == 200, (
        f"POST /scans?queue=true must succeed under the documented concurrent read load once "
        f"the pool is sized by the fixed formula, got {scan_response.status_code}: "
        f"{scan_response.text}"
    )
    body = scan_response.json()
    assert body.get("queued") is True
    assert body.get("scan_id")
    assert body.get("job_id")
