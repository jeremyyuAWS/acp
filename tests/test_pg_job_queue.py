"""The job queue, against the database it actually runs on.

THE GAP. Every job-queue test in this suite uses `isolated_store`, which is SQLite. `_PgAdapter`
and `_SQLiteAdapter` implement `claim_job` DIFFERENTLY, and only one of them runs in production:

    Postgres   UPDATE jobs SET … WHERE id = (SELECT id FROM jobs WHERE status='queued'
               ORDER BY priority, run_after FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id
    SQLite     SELECT the next id, then a conditional UPDATE … WHERE id=%s AND status='queued'

Nothing in tests/ referenced `supports_skip_locked` before this file, so the Postgres branch had
NO test coverage at all — including tests/test_job_skip_locked.py, whose docstring says "Tests
for SKIP LOCKED claim path" while running the SQLite CAS branch.

That matters more than a missing line of coverage. SKIP LOCKED exists to let N workers claim
concurrently without blocking or double-claiming, and SQLite cannot express the failure it
prevents: it serialises writers, so the two-step CAS is safe there by accident of the engine
rather than by the code being right. Every lease and ownership guard added this week — #1075's
touch_job predicate, #1080's outcome-write predicate — was likewise verified only against
semantics production does not use. Those predicates are built by CONCATENATING a fragment
(`_CLAIM_OWNED`) onto each statement, so "does the composed SQL do what it says on the real
engine" is a question SQLite was never able to answer.

WHAT IS HERE. Only the behaviours that differ by engine or need real concurrency. This is not a
port of the whole queue suite: re-running assertions that are engine-independent against a second
database buys nothing but runtime.

Runs in the `Postgres integration (schema/lock regressions)` CI job, which sets DATABASE_URL and
ACP_REQUIRE_PG=1. Skips locally without DATABASE_URL; test_we_are_really_on_postgres makes a
misconfigured run FAIL rather than skip, because a queue-concurrency file that silently tested
SQLite would be worse than no file.
"""
from __future__ import annotations

import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store as store_mod  # noqa: E402

_PG = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _PG.startswith("postgres"),
    reason="needs a real PostgreSQL; set DATABASE_URL (the Postgres integration CI job does).")


@pytest.fixture()
def pg():
    """A Store on the real Postgres, with the queue tables emptied first.

    TRUNCATE rather than a fresh database per test: the schema is already applied (Store's own
    init_schema saw to that) and re-creating 40 tables per test would dominate the runtime of a
    file whose point is concurrency. CASCADE because jobs/scan_runs are referenced elsewhere;
    acp_schema_version is deliberately spared, since dropping it would make the next Store()
    re-run the whole migration.
    """
    import psycopg2
    st = store_mod.Store()
    conn = psycopg2.connect(_PG)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("""
            SELECT string_agg(quote_ident(table_name), ', ')
            FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
              AND table_name <> 'acp_schema_version'
        """)
        names = cur.fetchone()[0]
        if names:
            cur.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
    conn.close()
    return st


def _enqueue_many(st, n, job_type="t_pg"):
    return [st.enqueue_job(job_type, {"i": i}) for i in range(n)]


# ── the file cannot silently degrade to SQLite ────────────────────────────────────────────────

def test_we_are_really_on_postgres(pg):
    """Everything below is about a branch SQLite does not take. If this file ever ran against
    SQLite it would pass — the CAS path satisfies the same assertions — while proving nothing
    about production. So assert the engine, not just the results."""
    assert pg._db.supports_skip_locked is True, (
        f"this file is running against {type(pg._db).__name__}, which takes the CAS claim path — "
        "every assertion below would pass without exercising the SQL that production runs")
    assert type(pg._db).__name__ == "_PgAdapter"


# ── concurrency: the reason SKIP LOCKED exists ────────────────────────────────────────────────

def test_concurrent_workers_never_claim_the_same_job_twice(pg):
    """THE test this file exists for, and the one SQLite cannot express.

    Eight workers race for forty jobs. SKIP LOCKED's guarantee is that each row goes to exactly
    one claimant and no worker blocks behind another's row lock. A double-claim means two workers
    process the same documents; a lost job means a scan never finishes.
    """
    ids = _enqueue_many(pg, 40)
    claimed: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def worker(name):
        start.wait()                       # maximise the overlap rather than hoping for it
        got = []
        while True:
            job = pg.claim_job(f"w{name}")
            if job is None:
                break
            got.append(job["id"])
        with lock:
            claimed.extend(got)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(worker, range(8)))

    counts = Counter(claimed)
    dupes = {k: v for k, v in counts.items() if v > 1}
    assert not dupes, f"jobs claimed more than once: {dupes}"
    assert set(claimed) == set(ids), (
        f"claimed {len(set(claimed))} of {len(ids)} jobs — "
        f"missing {sorted(set(ids) - set(claimed))[:5]}")


def test_concurrent_claims_do_not_lose_attempt_increments(pg):
    """claim_job increments `attempts` in the same statement that claims. If that were racy, a
    retried job could keep claiming forever without ever exhausting its attempts — the queue's
    only defence against an infinite retry loop."""
    [jid] = _enqueue_many(pg, 1)

    for _ in range(4):                     # claim, release, claim again
        job = pg.claim_job("w1")
        assert job is not None
        pg.fail_job(jid, "transient", backoff_seconds=0,
                    worker_id="w1", attempt=job["attempts"])

    assert pg.get_job(jid)["attempts"] == 4, (
        f"attempts is {pg.get_job(jid)['attempts']} after four claims — increments were lost")


def test_a_second_worker_takes_over_a_reclaimed_job_exactly_once(pg):
    """The handover the lease exists for, on the real engine: after the sweeper requeues, exactly
    one of several racing workers gets it."""
    [jid] = _enqueue_many(pg, 1)
    pg.claim_job("worker-A")
    assert pg.reclaim_stuck_jobs(lease_seconds=0) == 1

    winners = []
    lock = threading.Lock()

    def take(n):
        job = pg.claim_job(f"taker{n}")
        if job:
            with lock:
                winners.append(job["locked_by"])

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(take, range(6)))

    assert len(winners) == 1, f"{len(winners)} workers claimed the same reclaimed job: {winners}"


# ── the guards added this week, on the engine that runs them ──────────────────────────────────

def test_lease_renewal_ownership_holds_on_postgres(pg):
    """#1075's predicate, composed into real SQL. Verified until now only on SQLite."""
    [jid] = _enqueue_many(pg, 1)
    a = pg.claim_job("worker-A")
    assert pg.reclaim_stuck_jobs(lease_seconds=0) == 1
    b = pg.claim_job("worker-B")
    assert b["attempts"] > a["attempts"]

    before = pg.get_job(jid)["lease_expires_at"]
    pg.touch_job(jid, worker_id="worker-A", attempt=a["attempts"])     # the zombie
    assert pg.get_job(jid)["lease_expires_at"] == before, (
        "a reclaimed worker extended the new holder's lease — while it does, the new holder's "
        "own death can never be detected")

    pg.touch_job(jid, worker_id="worker-B", attempt=b["attempts"])     # the real holder
    assert pg.get_job(jid)["lease_expires_at"] != before


def test_outcome_ownership_holds_on_postgres(pg):
    """#1080's predicate, which is built by concatenating _CLAIM_OWNED onto each statement —
    exactly the kind of construction that can compose differently on another engine."""
    [jid] = _enqueue_many(pg, 1)
    a = pg.claim_job("worker-A")
    assert pg.reclaim_stuck_jobs(lease_seconds=0) == 1
    pg.claim_job("worker-B")

    assert pg.complete_job(jid, worker_id="worker-A", attempt=a["attempts"]) is False
    assert pg.get_job(jid)["status"] == "running", "a stale claim completed a live job"

    assert pg.mark_job_cancelled(jid, worker_id="worker-A", attempt=a["attempts"]) is False
    assert pg.fail_job(jid, "stale", backoff_seconds=0,
                       worker_id="worker-A", attempt=a["attempts"]) == "stale"
    assert pg.get_job(jid)["status"] == "running"


def test_the_current_holder_still_completes_on_postgres(pg):
    """The invariant beside it: tightening the predicate must not break the ordinary path."""
    [jid] = _enqueue_many(pg, 1)
    job = pg.claim_job("worker-A")
    assert pg.complete_job(jid, worker_id="worker-A", attempt=job["attempts"]) is True
    assert pg.get_job(jid)["status"] == "done"


# ── claim ORDER, which the two engines express differently ────────────────────────────────────

def test_priority_then_run_after_ordering_holds_on_postgres(pg):
    """Both branches carry `ORDER BY priority, run_after`, but Postgres's sits inside a subquery
    with FOR UPDATE SKIP LOCKED — a construction whose ordering interacts with row skipping.
    Worth pinning on the engine that has it."""
    low = pg.enqueue_job("t_pg", {"n": "low"}, priority=9)
    high = pg.enqueue_job("t_pg", {"n": "high"}, priority=1)

    first = pg.claim_job("w1")
    assert first["id"] == high, "priority ordering was not honoured by the SKIP LOCKED claim"
    second = pg.claim_job("w1")
    assert second["id"] == low


def test_a_job_still_in_backoff_is_not_claimed_on_postgres(pg):
    """run_after gating, inside the same subquery. A job claimed before its backoff elapses
    retries immediately and defeats the retry policy."""
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    pg.enqueue_job("t_pg", {"n": "later"}, run_after=future)

    assert pg.claim_job("w1") is None, "claimed a job that is still in backoff"


def test_an_empty_queue_returns_none_rather_than_raising(pg):
    """The Postgres branch returns None when the subquery selects nothing — a different code path
    from SQLite's, which checks a fetchone() before updating."""
    assert pg.claim_job("w1") is None
