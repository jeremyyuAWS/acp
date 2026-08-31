"""A result write is fenced by the job attempt that produced it.

WHAT WAS UNFENCED. #1075 and #1080 fenced the QUEUE OUTCOME writes — complete_job, fail_job and
mark_job_cancelled all require (worker_id, attempt) and refuse a stale claim. The conclusion drawn
from that, including by me in a status report, was "a superseded worker cannot publish". True of
the job row. False of the RESULT: store.save_file_result took no worker, no attempt and no job. It
is an UPSERT on (scan_id, file) that does far more than change a score — it DELETEs the file's
issue_records and re-inserts them, rewrites its rule traces, manifest, PII findings and inventory
row. So a stale write did not nudge a number, it replaced the finding set a reviewer was reading,
and it feeds count_files_done, which gates scan_finalize.

WHICH WORKER IS ACTUALLY DANGEROUS, because the intuitive answer is wrong. A SIGSEGV'd worker is
the SAFE case: a dead process writes nothing. The hazard is a worker that is alive but no longer
owns the job:

  (a) slow, not dead — the lease expires, reclaim_stuck_jobs requeues, another worker takes
      attempt 2, and the original handler runs to completion and writes its result. Its
      complete_job is correctly refused. The row it already wrote was not.

  (b) the timeout orphan — _analyse_and_persist_one starts the work on a DAEMON thread and joins
      it for ACP_SCAN_FILE_TIMEOUT_S. On expiry it records status='error' and moves on but never
      cancels the thread, which keeps running and writes later. Its own comment justified this
      ("save_file_result upserts, so if the orphaned worker thread finishes late with a real
      result it simply replaces the error row"), and that reasoning is sound WITHIN ONE ATTEMPT.
      Across attempts — which reclaim makes routine — it is the bug.

THE SHAPE OF THE FIX, and the two things it must not do. file_records now carries the job id and
attempt that wrote it, and a write is refused only when the SAME job has already written a HIGHER
attempt.

  - it must not block a DIFFERENT job. Attempt counters are per-job. rescore_file walks the same
    (scan_id, file) row under its own counter, so a plain attempt comparison would refuse a
    first-attempt re-score landing on a row written by a scan job's second attempt — a deliberate
    user action dropped by a guard meant to stop an abandoned thread. Pinned below.
  - a refusal must touch NOTHING. The dependent writes happen after the upsert is known to have
    applied; a refusal that still ran the DELETE would do the exact damage it was refusing.
    Pinned below, because it is the assertion that distinguishes a real fence from a returned
    False.

NOT AT ISSUE: store._record_dead_scan_files also calls save_file_result and WAS already fenced —
but in its caller, not in itself. #1080 put a _claim_is_current bail in fail_job ahead of the side
effects. That protects today's only caller and would not protect a second one, so it now passes
its own job too.
"""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

API = Path(__file__).resolve().parent.parent / "api"


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "fencing.db")
    return store_mod.Store()


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


def _job(st, jid):
    return st.get_job(jid)


def _scan_with_one_file(st, sid="s-fence"):
    st.init_scan_run(sid, "drive", 1, "2026-08-31T00:00:00Z", "r", "h",
                     owner="demo@example.com", status="running")
    return st.enqueue_job("scan_file", {"scan_id": sid, "file": "report.docx"}, scan_id=sid)


def _expire(st, jid):
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET lease_expires_at=%s, locked_at=%s WHERE id=%s",
                       ("1970-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00", jid))


def _superseded_then_retaken(st, sid):
    """Drive one job through the exact sequence the audit describes, and hand back both views of
    it: the job as w8 still believes it to be (attempt 1) and as w6 now holds it (attempt 2)."""
    jid = _scan_with_one_file(st, sid)
    st.claim_job("w8")
    stale = _job(st, jid)                     # what the slow worker is still carrying
    _expire(st, jid)
    assert st.reclaim_stuck_jobs() == 1
    st.claim_job("w6")
    return stale, _job(st, jid)


# ── the finding ───────────────────────────────────────────────────────────────────────────────

def test_a_worker_that_lost_its_claim_cannot_overwrite_the_replacements_result(st):
    """THE audit finding, in the shape reclaim makes routine. w8 is slow, not dead."""
    sid = "s-fence"
    stale, current = _superseded_then_retaken(st, sid)

    assert st.save_file_result(sid, _result("report.docx", "certifiable", 98),
                               "2026-08-31T01:00:00Z", job=current) is True
    # w8, still alive and unaware, finishes its own analysis and persists it.
    assert st.save_file_result(sid, _result("report.docx", "error", None),
                               "2026-08-31T00:05:00Z", job=stale) is False

    assert _row(st, sid, "report.docx")["status"] == "certifiable"


def test_a_refused_write_leaves_the_finding_set_untouched(st):
    """The assertion that separates a fence from a return value. save_file_result DELETEs
    issue_records before re-inserting; a refusal that reached that line would destroy the findings
    it was refusing to replace — most of the harm, none of the benefit."""
    sid = "s-fence-issues"
    stale, current = _superseded_then_retaken(st, sid)

    st.save_file_result(sid, _result("report.docx", "uncertain", 60,
                                     issues=("real-1", "real-2", "real-3")),
                        "2026-08-31T01:00:00Z", job=current)
    assert _issues(st, sid, "report.docx") == ["real-1", "real-2", "real-3"]

    st.save_file_result(sid, _result("report.docx", "error", None, issues=("stale-1",)),
                        "2026-08-31T00:05:00Z", job=stale)

    assert _issues(st, sid, "report.docx") == ["real-1", "real-2", "real-3"]


def test_the_timeout_orphans_own_earlier_attempt_cannot_bury_a_good_result(st):
    """Hazard (b). The watchdog writes status='error' for the file it gave up on, whoever else may
    have completed it since."""
    sid = "s-fence-timeout"
    stale, current = _superseded_then_retaken(st, sid)
    st.save_file_result(sid, _result("report.docx", "certifiable", 99),
                        "2026-08-31T01:00:00Z", job=current)

    # What handlers._analyse_and_persist_one writes when its watchdog fires on attempt 1.
    assert st.save_file_result(sid, {"file": "report.docx", "engine": "n/a", "status": "error",
                                     "score": None, "compliant": 0, "skipped_rules": 0,
                                     "issues": [], "drive_file_id": None},
                               "2026-08-31T00:05:00Z", job=stale) is False
    assert _row(st, sid, "report.docx")["status"] == "certifiable"


# ── the controls: everything the fence must NOT block ─────────────────────────────────────────

def test_the_same_attempt_still_replaces_its_own_error_row(st):
    """Deliberate, and the reason the comparison is >= and not >. Inside ONE attempt the late
    orphan replacing the watchdog's error row is the documented, useful behaviour."""
    sid = "s-fence-same"
    jid = _scan_with_one_file(st, sid)
    st.claim_job("w8")
    job = _job(st, jid)
    st.save_file_result(sid, _result("report.docx", "error", None), "2026-08-31T00:05:00Z",
                        job=job)
    assert st.save_file_result(sid, _result("report.docx", "certifiable", 97),
                               "2026-08-31T00:09:00Z", job=job) is True
    assert _row(st, sid, "report.docx")["score"] == 97


def test_a_later_attempt_of_the_same_job_still_wins(st):
    sid = "s-fence-newer"
    stale, current = _superseded_then_retaken(st, sid)
    st.save_file_result(sid, _result("report.docx", "error", None), "2026-08-31T00:05:00Z",
                        job=stale)
    assert st.save_file_result(sid, _result("report.docx", "certifiable", 95),
                               "2026-08-31T01:00:00Z", job=current) is True
    assert _row(st, sid, "report.docx")["status"] == "certifiable"


def test_a_different_job_is_never_refused_however_low_its_attempt(st):
    """The false refusal a bare attempt comparison would produce. A user clicks Re-scan after
    self-remediating; rescore_file is a fresh job on attempt 1, and it must land on a row a scan
    job's attempt 2 wrote."""
    sid = "s-fence-rescore"
    _stale, current = _superseded_then_retaken(st, sid)
    st.save_file_result(sid, _result("report.docx", "uncertain", 60), "2026-08-31T01:00:00Z",
                        job=current)
    assert (current.get("attempts") or 0) >= 2

    rid = st.enqueue_job("rescore_file", {"scan_id": sid, "file": "report.docx"}, scan_id=sid)
    st.claim_job("w9")
    rescore = _job(st, rid)
    assert (rescore.get("attempts") or 0) == 1

    assert st.save_file_result(sid, _result("report.docx", "certifiable", 100),
                               "2026-08-31T02:00:00Z", job=rescore) is True
    assert _row(st, sid, "report.docx")["score"] == 100


def test_a_caller_with_no_job_writes_exactly_as_it_did_before(st):
    """111 call sites across the suite pass no job, and the parameter is keyword-only with a
    default so none of them had to change. An unstamped write must behave as it always did."""
    sid = "s-fence-nojob"
    _scan_with_one_file(st, sid)
    assert st.save_file_result(sid, _result("report.docx", "error", None),
                               "2026-08-31T00:00:00Z") is True
    assert st.save_file_result(sid, _result("report.docx", "certifiable", 88),
                               "2026-08-31T02:00:00Z") is True
    assert _row(st, sid, "report.docx")["score"] == 88


def test_an_unstamped_write_does_not_erase_the_stamp_and_reopen_the_row(st):
    """Why the columns are set with COALESCE rather than assigned from EXCLUDED. A plain
    assignment would let any unstamped caller blank them, and the next stale writer would sail
    through the IS NULL clause — a guard a passer-by can switch off is not a guard."""
    sid = "s-fence-coalesce"
    stale, current = _superseded_then_retaken(st, sid)
    st.save_file_result(sid, _result("report.docx", "certifiable", 98), "2026-08-31T01:00:00Z",
                        job=current)
    st.save_file_result(sid, _result("report.docx", "uncertain", 70), "2026-08-31T01:30:00Z")

    row = _row(st, sid, "report.docx")
    assert row["score"] == 70
    assert row["written_job"] == current["id"] and row["written_attempt"] == current["attempts"]
    assert st.save_file_result(sid, _result("report.docx", "error", None),
                               "2026-08-31T00:05:00Z", job=stale) is False


def test_a_row_written_before_the_columns_existed_stays_writable(st):
    """Migration. Existing rows carry NULL, and NULL must ALLOW rather than block — an old row
    that became unwritable would be a worse bug than the one being fixed."""
    sid = "s-fence-legacy"
    stale, _current = _superseded_then_retaken(st, sid)
    st.save_file_result(sid, _result("report.docx", "error", None), "2026-08-31T00:00:00Z")
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE file_records SET written_job=NULL, written_attempt=NULL "
                            "WHERE scan_id=%s", (sid,))
    assert st.save_file_result(sid, _result("report.docx", "certifiable", 91),
                               "2026-08-31T00:05:00Z", job=stale) is True
    assert _row(st, sid, "report.docx")["score"] == 91


def test_the_counter_that_gates_finalize_still_advances_on_a_refusal(st):
    """A refused write must not leave the run unfinalizable. The refusal happens only because a
    row is ALREADY there, so count_files_done is already satisfied by it — but the run gates on
    that count, so the claim is worth pinning rather than reasoning about."""
    sid = "s-fence-count"
    stale, current = _superseded_then_retaken(st, sid)
    st.save_file_result(sid, _result("report.docx", "certifiable", 98), "2026-08-31T01:00:00Z",
                        job=current)
    st.save_file_result(sid, _result("report.docx", "error", None), "2026-08-31T00:05:00Z",
                        job=stale)
    done, total = st.count_files_done(sid)
    assert done == total == 1


# ── the guard: production callers must identify themselves ────────────────────────────────────

def _production_call_sites():
    """Every save_file_result CALL under api/ — the definition and the tests excluded."""
    out = []
    for path in sorted(API.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name == "save_file_result":
                out.append((path.relative_to(API).as_posix(), node.lineno,
                            {k.arg for k in node.keywords}))
    return out


def test_every_production_caller_passes_its_job():
    """The fence is opt-in by construction — `job` is keyword-only with a default, because
    requiring it would have broken 111 call sites across 53 test files for no gain. That makes it
    silently skippable in production too, which is the failure this test exists to prevent: a new
    handler that forgets the kwarg gets an unfenced write and no error.

    It also keeps the audit honest. "Result writes are fenced" is only true if every writer that
    HAS a job passes one, and that is a fact about call sites, not about store.py.
    """
    sites = _production_call_sites()
    assert sites, "found no save_file_result calls under api/ — this guard has stopped guarding"
    missing = [(p, ln) for p, ln, kw in sites if "job" not in kw]
    assert not missing, (
        f"save_file_result called without job= at {missing}. Every production caller runs inside "
        f"a handler that already has the queue row; pass it so the write is fenced.")
