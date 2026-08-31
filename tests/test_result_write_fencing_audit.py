"""AUDIT PROBE (expected red): result writes are not fenced by the claim that authorised them.

#1075 and #1080 fenced the QUEUE OUTCOME writes — complete_job, fail_job, mark_job_cancelled all
require (worker_id, attempt) and refuse a stale claim. The conclusion drawn from that, including
by me, was "a superseded worker cannot publish". That is true of the job row and false of the
RESULT.

store.save_file_result(scan_id, f, completed_at) takes no worker, no attempt, no job. It is an
unconditional UPSERT on (scan_id, file), and it does more than change a score: it DELETEs the
file's issue_records and re-inserts them, and refreshes its rule traces. So a stale write does
not nudge a number, it replaces the finding set — and it feeds count_files_done, which gates
scan_finalize.

WHICH WORKER IS ACTUALLY DANGEROUS, because the intuitive answer is wrong. A SIGSEGV'd worker is
the SAFE case: a dead process writes nothing. The hazard is a worker that is alive but no longer
owns the job:

  (a) slow, not dead — the lease expires, reclaim_stuck_jobs requeues, another worker takes
      attempt 2, and the original handler runs to completion and writes its result. Its
      complete_job is correctly refused (#1080). The row it already wrote is not.

  (b) the timeout orphan — _analyse_and_persist_one starts the work on a daemon thread and
      join()s it for ACP_SCAN_FILE_TIMEOUT_S. On expiry it writes status='error' and moves on,
      but never cancels the thread. That thread keeps running and later writes through the same
      unfenced path. Its own comment justifies this ("save_file_result upserts, so if the
      orphaned worker thread finishes late with a real result it simply replaces the error row"),
      and the justification is sound WITHIN ONE ATTEMPT. Across attempts — which reclaim makes
      routine — it is the bug.

The timeout path is also the one that can overwrite a GOOD result with an error: it writes
status='error' unconditionally for the file it gave up on, whoever else may have completed it.

NOT AT ISSUE: store._record_dead_scan_files also calls save_file_result, and IS fenced — but in
its caller, not itself. #1080 put a _claim_is_current bail in fail_job before the side effects.
That protects today's only caller and would not protect a second one.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from conftest import held  # noqa: E402


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "fencing.db")
    return store_mod.Store()


def _result(name, status, score, issues=()):
    return {"file": name, "engine": "docx", "status": status, "score": score,
            "compliant": 1 if status == "certifiable" else 0, "skipped_rules": 0,
            "issues": [{"rule_id": r, "wcag": "1.1.1", "severity": "SERIOUS", "detail": r}
                       for r in issues]}


def _row(st, sid, name):
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT status, score FROM file_records WHERE scan_id=%s AND file=%s",
                       (sid, name))
        return st._db.fetchone(cur)


def _issue_count(st, sid, name):
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT COUNT(*) AS n FROM issue_records WHERE scan_id=%s AND file=%s",
                       (sid, name))
        return (st._db.fetchone(cur) or {}).get("n") or 0


def _scan_with_one_file(st, sid="s-fence"):
    st.init_scan_run(sid, "drive", 1, "2026-08-31T00:00:00Z", "r", "h",
                     owner="demo@example.com", status="running")
    return st.enqueue_job("scan_file", {"scan_id": sid, "file": "report.docx"}, scan_id=sid)


def test_a_worker_that_lost_its_claim_cannot_overwrite_the_replacement_s_result(st):
    """THE audit finding, in the shape reclaim makes routine.

    w8 is slow, not dead. Its lease expires, the sweeper requeues, w6 takes attempt 2 and
    completes the file correctly. w8 then finishes and writes — with no claim, over a result it
    does not own."""
    sid = "s-fence"
    jid = _scan_with_one_file(st, sid)

    st.claim_job("w8")                                     # attempt 1
    with st._db.cursor() as cur:                           # its lease expires
        st._db.execute(cur, "UPDATE jobs SET lease_expires_at=%s, locked_at=%s WHERE id=%s",
                       ("1970-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00", jid))
    assert st.reclaim_stuck_jobs() == 1

    st.claim_job("w6")                                     # attempt 2 takes over
    st.save_file_result(sid, _result("report.docx", "certifiable", 98), "2026-08-31T01:00:00Z")
    assert _row(st, sid, "report.docx")["status"] == "certifiable"

    # w8, still alive and unaware, finishes its own analysis and persists it.
    st.save_file_result(sid, _result("report.docx", "error", None, issues=("stale-a", "stale-b")),
                        "2026-08-31T00:05:00Z")

    assert _row(st, sid, "report.docx")["status"] == "certifiable", (
        "a worker that no longer holds the claim overwrote the replacement's result — its "
        "complete_job would be refused (#1080), but save_file_result takes no claim at all")


def test_a_stale_write_cannot_replace_the_finding_set(st):
    """The blast radius is not one column. save_file_result DELETEs issue_records for the file
    and re-inserts, so a stale write substitutes the findings a reviewer is looking at."""
    sid = "s-fence-issues"
    jid = _scan_with_one_file(st, sid)
    st.claim_job("w8")
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET lease_expires_at=%s, locked_at=%s WHERE id=%s",
                       ("1970-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00", jid))
    st.reclaim_stuck_jobs()
    st.claim_job("w6")

    st.save_file_result(sid, _result("report.docx", "uncertain", 60, issues=("real-1", "real-2",
                                                                            "real-3")),
                        "2026-08-31T01:00:00Z")
    assert _issue_count(st, sid, "report.docx") == 3

    st.save_file_result(sid, _result("report.docx", "error", None, issues=("stale-1",)),
                        "2026-08-31T00:05:00Z")

    assert _issue_count(st, sid, "report.docx") == 3, (
        "a stale write replaced the file's finding set, not just its score")


def test_the_timeout_row_cannot_overwrite_a_completed_result(st):
    """The timeout path writes status='error' for the file it gave up on, unconditionally. If
    another attempt already completed that file, the give-up row lands on top of it."""
    sid = "s-fence-timeout"
    _scan_with_one_file(st, sid)
    st.save_file_result(sid, _result("report.docx", "certifiable", 99), "2026-08-31T01:00:00Z")

    # What handlers._analyse_and_persist_one writes when its watchdog fires.
    st.save_file_result(sid, {"file": "report.docx", "engine": "n/a", "status": "error",
                              "score": None, "compliant": 0, "skipped_rules": 0, "issues": [],
                              "drive_file_id": None}, "2026-08-31T00:05:00Z")

    assert _row(st, sid, "report.docx")["status"] == "certifiable", (
        "a per-file timeout recorded an error over a file another attempt had already assessed "
        "successfully")


def test_the_control_a_legitimate_rescan_still_replaces_its_own_row(st):
    """The control, so a fix cannot be 'refuse every second write'. Re-running a file under the
    CURRENT claim must still update it — that is what makes a retry useful."""
    sid = "s-fence-control"
    _scan_with_one_file(st, sid)
    st.save_file_result(sid, _result("report.docx", "error", None), "2026-08-31T00:00:00Z")
    st.save_file_result(sid, _result("report.docx", "certifiable", 97), "2026-08-31T02:00:00Z")
    assert _row(st, sid, "report.docx")["status"] == "certifiable"
    assert _row(st, sid, "report.docx")["score"] == 97
