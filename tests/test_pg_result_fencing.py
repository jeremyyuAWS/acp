"""The result-write fence, against the database it actually runs on.

WHY A SECOND FILE FOR ONE PREDICATE. tests/test_result_write_fencing.py proves the fence on
SQLite, which is what the four backend shards run. The fence itself is a WHERE clause on
`ON CONFLICT … DO UPDATE`, plus a read of `cursor.rowcount` to tell an applied write from a
refused one — and both of those are engine behaviour, not application logic:

  - SQLite and psycopg2 are free to disagree about what rowcount means after an upsert whose
    WHERE excluded the row. The refusal is decided by that number, so if Postgres returned 1
    there, the fence would be OFF in production and every SQLite test would still pass.
  - `COALESCE(EXCLUDED.x, tbl.x)` inside DO UPDATE SET, and `tbl.x <> EXCLUDED.x` inside its
    WHERE, are the two constructs the predicate is built from.

Production runs Postgres. A guard verified only on the engine production does not use is a guard
whose most important claim has never been tested — the same gap tests/test_pg_job_queue.py was
written for, one layer up.

WHY NOT IN THAT FILE. Its `pg` fixture TRUNCATEs every base table in `public` before each test.
That is defensible for a queue-concurrency file and it is not something this one needs: these
tests seed their own uniquely-named scan and assert only on their own rows, so they add no
destructive step to the job. Nothing here drops, truncates or deletes.

Runs in the `Postgres integration (schema/lock regressions)` CI job. Skips locally without
DATABASE_URL; test_we_are_really_on_postgres makes a misconfigured run FAIL rather than skip.
"""
from __future__ import annotations

import os
import sys
import uuid
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
    """A Store on the real Postgres. No cleanup, because there is nothing to clean up: every test
    below works on a scan id nobody else uses."""
    return store_mod.Store()


@pytest.fixture()
def sid():
    return f"pgfence-{uuid.uuid4().hex[:12]}"


def _result(name, status, score, issues=()):
    return {"file": name, "engine": "docx", "status": status, "score": score,
            "compliant": 1 if status == "certifiable" else 0, "skipped_rules": 0,
            "issues": [{"ruleId": r, "wcag": "1.1.1", "severity": "SERIOUS", "detail": r}
                       for r in issues]}


def _row(st, sid, name):
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT status, score, written_job, written_attempt "
                            "FROM file_records WHERE scan_id=%s AND file=%s", (sid, name))
        return st._db.fetchone(cur)


def _issues(st, sid, name):
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT rule_id FROM issue_records WHERE scan_id=%s AND file=%s "
                            "ORDER BY rule_id", (sid, name))
        return [r["rule_id"] for r in st._db.fetchall(cur)]


def _two_views_of_one_job(st, sid, job_type="scan_file"):
    """The two job dicts a supersession leaves in play: the row as the slow worker w8 still holds
    it (attempt 1) and as w6 now holds it after a reclaim (attempt 2).

    BUILT, not driven through claim_job/reclaim_stuck_jobs, and deliberately so. Both of those are
    ESTATE-WIDE — claim_job takes whichever queued row sorts first anywhere in the database, and
    reclaim sweeps every expired lease — and this database is shared with the other Postgres file
    and not truncated here. Driving them would make these tests depend on what else happens to be
    queued, and would mutate other tests' rows to set up an assertion that has nothing to do with
    the lease lifecycle.

    That lifecycle is covered where isolation is real: tests/test_result_write_fencing.py runs the
    genuine claim → expire → reclaim → re-claim sequence against a private SQLite store. What is
    left to prove HERE is the SQL predicate on the engine production uses, and it reads exactly
    two fields off these dicts.
    """
    st.init_scan_run(sid, "drive", 1, "2026-08-31T00:00:00Z", "r", "h",
                     owner="demo@example.com", status="running")
    jid = st.enqueue_job(job_type, {"scan_id": sid, "file": "report.docx"}, scan_id=sid)
    row = st.get_job(jid)
    assert row and row["id"] == jid
    return {**row, "attempts": 1}, {**row, "attempts": 2}


def test_we_are_really_on_postgres(pg):
    """This file would pass on SQLite — that is precisely the state it exists to rule out."""
    assert pg._db.supports_skip_locked is True, (
        "DATABASE_URL is set but the Store is not on Postgres; these assertions would prove "
        "nothing about production")


def test_rowcount_reports_a_refused_upsert_as_zero(pg, sid):
    """The single engine fact the whole fence rests on. If psycopg2 reported 1 for an upsert
    whose DO UPDATE WHERE excluded the row, save_file_result would read it as applied and the
    fence would be silently off in production while SQLite stayed green."""
    stale, current = _two_views_of_one_job(pg, sid)
    assert pg.save_file_result(sid, _result("report.docx", "certifiable", 98),
                               "2026-08-31T01:00:00Z", job=current) is True
    assert pg.save_file_result(sid, _result("report.docx", "error", None),
                               "2026-08-31T00:05:00Z", job=stale) is False
    assert _row(pg, sid, "report.docx")["status"] == "certifiable"


def test_a_refused_write_leaves_the_finding_set_untouched(pg, sid):
    stale, current = _two_views_of_one_job(pg, sid)
    pg.save_file_result(sid, _result("report.docx", "uncertain", 60,
                                     issues=("real-1", "real-2", "real-3")),
                        "2026-08-31T01:00:00Z", job=current)
    assert _issues(pg, sid, "report.docx") == ["real-1", "real-2", "real-3"]
    pg.save_file_result(sid, _result("report.docx", "error", None, issues=("stale-1",)),
                        "2026-08-31T00:05:00Z", job=stale)
    assert _issues(pg, sid, "report.docx") == ["real-1", "real-2", "real-3"]


def test_coalesce_keeps_the_stamp_when_an_unstamped_write_lands(pg, sid):
    """`COALESCE(EXCLUDED.written_job, file_records.written_job)` inside DO UPDATE SET, on the
    real engine. If it assigned NULL instead, the next stale write would pass the IS NULL clause
    and the fence would be one unstamped caller away from off."""
    stale, current = _two_views_of_one_job(pg, sid)
    pg.save_file_result(sid, _result("report.docx", "certifiable", 98), "2026-08-31T01:00:00Z",
                        job=current)
    pg.save_file_result(sid, _result("report.docx", "uncertain", 70), "2026-08-31T01:30:00Z")
    row = _row(pg, sid, "report.docx")
    assert row["score"] == 70
    assert row["written_job"] == current["id"]
    assert row["written_attempt"] == current["attempts"]
    assert pg.save_file_result(sid, _result("report.docx", "error", None),
                               "2026-08-31T00:05:00Z", job=stale) is False


def test_a_different_job_is_never_refused_however_low_its_attempt(pg, sid):
    """`file_records.written_job <> EXCLUDED.written_job` on the real engine — the clause that
    keeps a first-attempt re-score from being refused by a scan job's second attempt."""
    _stale, current = _two_views_of_one_job(pg, sid)
    pg.save_file_result(sid, _result("report.docx", "uncertain", 60), "2026-08-31T01:00:00Z",
                        job=current)
    rid = pg.enqueue_job("rescore_file", {"scan_id": sid, "file": "report.docx"}, scan_id=sid)
    rescore = {**pg.get_job(rid), "attempts": 1}
    assert rescore["id"] != current["id"]
    assert pg.save_file_result(sid, _result("report.docx", "certifiable", 100),
                               "2026-08-31T02:00:00Z", job=rescore) is True
    assert _row(pg, sid, "report.docx")["score"] == 100
