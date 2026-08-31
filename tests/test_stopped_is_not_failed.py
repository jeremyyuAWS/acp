"""A job someone STOPPED is not a job that FAILED, and the dead-letter view must say so.

WHAT WAS WRONG. `_end_running_scan` — which both `cancel_scan` and `supersede_scan` route
through — sets `status='dead'` on every queued/running job of the scan. Its own comment records
the consequence as deliberate:

    Safe to set both. The worker's cancellation path calls mark_job_cancelled(), whose UPDATE is
    guarded `status NOT IN ('done','dead','cancelled')`, so against a job this already marked
    'dead' that write no-ops and the job KEEPS its 'dead' status — dead-letter accounting is
    unchanged.

Unchanged, and wrong for the person reading it. `dead_letter_breakdown` answers "why are jobs
dying" — it is the operator's incident view and the source of Monitor's dead-letter banner. Every
Stop press landed in that answer as a failure: pressing Stop on a 200-document scan added 200
rows to `by_type`, inflated `affected_runs` and `total_attempts`, and grouped them under whatever
`last_error` happened to be on the row at the time.

A pressed button is not an incident. A diagnostic that cannot tell a decision from a fault makes
the real faults harder to see, which is the opposite of what it is for.

THE DATA WAS ALREADY THERE. Those rows carry `cancel_requested_at`, set by the same statement
that marks them dead. Nothing read it that way. So this is not new bookkeeping — it is reading
what was already recorded.

THREE STATES, which is the vocabulary the queue lacked:

    requested   cancel_requested_at is set. Work may still be running.
    observed    a worker's check_cancel() raised. That execution knows.
    stopped     the row is terminal AND cancel_requested_at is set — nothing belonging to this
                job can still run or write, and it ended by decision rather than by fault.

`stopped` is the one that had no representation anywhere. It does now.
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
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "stopped.db")
    return store_mod.Store()


def _scan_with_jobs(st, sid, n, owner="demo@example.com"):
    st.init_scan_run(sid, "drive", n, "2026-08-31T00:00:00Z", "rubric", "hash",
                     owner=owner, status="running")
    return [st.enqueue_job("scan_file", {"file": f"f{i}.docx"}, scan_id=sid) for i in range(n)]


# ── a real failure is still a failure ─────────────────────────────────────────────────────────

def test_a_genuine_dead_letter_is_still_counted_as_one(st):
    """The control, first. Narrowing the failure query must not make it stop reporting failures —
    that would trade a misleading number for a blind one."""
    _scan_with_jobs(st, "s-fail", 1)
    job = st.claim_job("w1")
    st.fail_job(job["id"], "drive said no", force_dead=True, **held(st, job["id"]))

    out = st.dead_letter_breakdown()
    assert out["by_type"].get("scan_file") == 1, f"a real failure vanished: {out['by_type']}"
    assert any("drive said no" in (g["error"] or "") for g in out["top_errors"])
    assert out["failed"]["n"] == 1
    assert out["failed"]["affected_runs"] == 1
    assert out["stopped"]["n"] == 0, "a failure was counted as a stop"


# ── a stop is not ─────────────────────────────────────────────────────────────────────────────

def test_stopping_a_scan_does_not_add_failures(st):
    """THE regression. Before this, cancelling a scan added one 'failure' per outstanding job to
    the operator's why-are-jobs-dying view."""
    _scan_with_jobs(st, "s-stop", 5)
    st.claim_job("w1")                                  # one running, four queued
    assert st.cancel_scan("s-stop", owner="demo@example.com") is True

    out = st.dead_letter_breakdown()
    assert out["by_type"] == {}, (
        f"stopping a scan reported {sum(out['by_type'].values())} failures: {out['by_type']} — "
        "a pressed button is not an incident")
    assert out["top_errors"] == [], f"stopped jobs appeared as errors: {out['top_errors']}"
    assert out["failed"]["n"] == 0, (
        "the headline failure count still counted the stop — this is the number QueuePanel "
        "renders as 'N jobs failed permanently'")


def test_the_stop_is_reported_rather_than_hidden(st):
    """Excluding them from failures must not make them invisible: the jobs really did end, and a
    user who stopped a run should be able to see that."""
    _scan_with_jobs(st, "s-stop2", 3)
    st.claim_job("w1")
    st.cancel_scan("s-stop2", owner="demo@example.com")

    out = st.dead_letter_breakdown()
    assert out["stopped"]["n"] == 3, f"stopped jobs were dropped entirely: {out['stopped']}"
    assert out["stopped"]["affected_runs"] == 1


def test_superseding_counts_as_stopped_not_failed(st):
    """supersede_scan routes through the same _end_running_scan. A newer run replacing an older
    one is a decision too — arguably more clearly so, since no human even chose it per-job."""
    _scan_with_jobs(st, "s-sup", 2)
    st.claim_job("w1")
    st.supersede_scan("s-sup", owner="demo@example.com")

    out = st.dead_letter_breakdown()
    assert out["by_type"] == {}, f"superseding reported failures: {out['by_type']}"
    assert out["stopped"]["n"] == 2


# ── the two must not contaminate each other ───────────────────────────────────────────────────

def test_a_failure_and_a_stop_in_the_same_estate_stay_separate(st):
    """The case that makes the distinction worth having: both present at once, which is the
    normal state of a busy estate and the one where an eyeball subtraction goes wrong."""
    _scan_with_jobs(st, "s-mixed-fail", 1)
    job = st.claim_job("w1")
    st.fail_job(job["id"], "real failure", force_dead=True, **held(st, job["id"]))

    _scan_with_jobs(st, "s-mixed-stop", 4)
    st.claim_job("w2")
    st.cancel_scan("s-mixed-stop", owner="demo@example.com")

    out = st.dead_letter_breakdown()
    assert sum(out["by_type"].values()) == 1, (
        f"expected exactly one failure beside four stops, got {out['by_type']}")
    assert out["failed"]["n"] == 1
    assert out["stopped"]["n"] == 4
    assert all("real failure" in (g["error"] or "") for g in out["top_errors"])


def test_owner_scoping_still_applies_to_both(st):
    """The scoping is a tenant boundary, not a filter — it must hold on the new count as well as
    the old one, or stopping a scan would leak a neighbour's job count."""
    _scan_with_jobs(st, "s-mine", 2, owner="mine@example.com")
    st.claim_job("w1")
    st.cancel_scan("s-mine", owner="mine@example.com")

    _scan_with_jobs(st, "s-theirs", 3, owner="theirs@example.com")
    st.claim_job("w2")
    st.cancel_scan("s-theirs", owner="theirs@example.com")

    mine = st.dead_letter_breakdown(owner="mine@example.com")
    assert mine["stopped"]["n"] == 2, (
        f"owner scoping does not apply to the stopped count: {mine['stopped']}")
    assert mine["stopped"]["affected_runs"] == 1


def test_purge_still_removes_stopped_rows_too(st):
    """Not a behaviour change, pinned because it would be easy to assume the new predicate
    narrowed the purge as well. It does not: purge_dead_jobs still clears the table, stops
    included, which is what "clear dead jobs" means to the person clicking it."""
    _scan_with_jobs(st, "s-purge", 2)
    st.claim_job("w1")
    st.cancel_scan("s-purge", owner="demo@example.com")

    assert st.purge_dead_jobs() == 2
    assert st.dead_letter_breakdown()["stopped"]["n"] == 0


def test_failed_n_and_by_type_cannot_drift_apart(st):
    """`failed.n` is redundant with sum(by_type.values()) and that is the point: it exists so the
    UI has a headline number to render instead of summing a dict, and the redundancy is only
    safe while the two queries carry the SAME predicate. Pin them equal, or a later edit to one
    WHERE clause leaves the banner and the breakdown disagreeing with nothing to catch it."""
    _scan_with_jobs(st, "s-drift-fail", 3)
    for _ in range(3):
        j = st.claim_job("w1")
        st.fail_job(j["id"], "nope", force_dead=True, **held(st, j["id"]))

    _scan_with_jobs(st, "s-drift-stop", 6)
    st.claim_job("w2")
    st.cancel_scan("s-drift-stop", owner="demo@example.com")

    out = st.dead_letter_breakdown()
    assert out["failed"]["n"] == sum(out["by_type"].values()) == 3
    assert out["failed"]["n"] == sum(g["n"] for g in out["top_errors"])


def test_a_worker_acknowledged_cancellation_also_reads_as_stopped(st):
    """The third state, reached the other way. mark_job_cancelled sets status='cancelled' when a
    worker's check_cancel() fires before _end_running_scan's UPDATE lands — same decision, a
    different terminal status. Both are `stopped`; neither is a failure."""
    _scan_with_jobs(st, "s-ack", 1)
    job = st.claim_job("w1")
    assert st.request_job_cancellation(job["id"]) is True
    assert st.mark_job_cancelled(job["id"], **held(st, job["id"])) is True
    assert st.get_job(job["id"])["status"] == "cancelled"

    out = st.dead_letter_breakdown()
    assert out["stopped"]["n"] == 1, (
        f"a worker-acknowledged cancellation was not counted as stopped: {out['stopped']}")
    assert out["failed"]["n"] == 0
