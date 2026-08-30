"""A superseded run must not come back and displace the run that replaced it (PRD H-03 #4:
"an older run cannot overwrite the newer run's published results").

The hazard, traced through the code rather than imagined:

1. `POST /scans?queue=true` supersedes the caller's in-flight run A and enqueues B.
2. `supersede_scan` marks A 'superseded' and A's jobs 'dead'. It does NOT set
   `cancel_requested_at` — the only field `worker.check_cancel()` reads — so a worker already
   executing A's job is never interrupted.
3. That worker runs to completion and calls `finalize_scan_run(A)`, which had no status test and
   wrote `status='done', completed_at=NOW()`.
4. `list_scans()` excludes 'superseded' but orders by `completed_at DESC`. A is now 'done' with
   the freshest timestamp in the estate, so it sorts AHEAD of B.

That is the collapse `supersede_scan`'s own docstring records from 2026-08-26 — "newest has 0
documents but a recent scan had 999" — reachable again through finalize instead of through
cancel_scan's completed_at.

The window is not the millisecond between accepting B and stopping A. It is the entire remaining
duration of A, because nothing stops A.

Both ends of a run are guarded here: finalize (a run completing after it was replaced) and
init_scan_run (a queued job claimed after its scan was replaced).
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"


def _iso(dt): return dt.isoformat()


@pytest.fixture()
def store(isolated_store):
    return isolated_store


def _make_run(store, sid, started, status="running"):
    store.init_scan_run(sid, "local", total=3, started_at=_iso(started),
                        rubric_name="WCAG 2.1 AA", rubric_hash="h", owner=OWNER, status=status)


def test_finalize_cannot_resurrect_a_superseded_run(store):
    """THE regression. A's worker finishes after A was superseded; A must stay superseded."""
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    _make_run(store, "A", t0)
    assert store.supersede_scan("A", owner=OWNER) is True
    assert store.get_scan("A", owner=OWNER)["run"]["status"] == "superseded"

    # The worker that never learned to stop arrives here, minutes later.
    store.finalize_scan_run("A", _iso(datetime.now(timezone.utc)))

    assert store.get_scan("A", owner=OWNER)["run"]["status"] == "superseded", (
        "a superseded run finalized itself back to 'done' — it will displace its replacement")


def test_the_superseded_run_does_not_displace_its_replacement_in_the_listing(store):
    """The user-visible consequence, asserted on the listing itself rather than on a status."""
    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)
    _make_run(store, "A", t0)
    _make_run(store, "B", t0 + timedelta(minutes=1))

    store.supersede_scan("A", owner=OWNER)
    # B completes first...
    store.finalize_scan_run("B", _iso(datetime.now(timezone.utc) - timedelta(minutes=1)))
    # ...then A's abandoned worker finishes, with a LATER completed_at than B's.
    store.finalize_scan_run("A", _iso(datetime.now(timezone.utc)))

    listed = [r["id"] for r in store.list_scans(owner=OWNER)]
    assert "A" not in listed, "the superseded run reappeared in the estate listing"
    assert listed and listed[0] == "B", (
        f"the superseded run displaced its replacement as the newest scan: {listed}")


def test_finalize_cannot_resurrect_a_cancelled_run(store):
    """The Stop button's path has the same shape and the same exposure."""
    _make_run(store, "C", datetime.now(timezone.utc) - timedelta(minutes=5))
    assert store.cancel_scan("C", owner=OWNER) is True
    store.finalize_scan_run("C", _iso(datetime.now(timezone.utc)))
    assert store.get_scan("C", owner=OWNER)["run"]["status"] == "cancelled"


def test_a_late_claim_cannot_promote_a_superseded_run_back_to_running(store):
    """The other end: a job sitting in the queue when its scan was replaced, claimed afterwards.
    init_scan_run's ON CONFLICT DO UPDATE set status unconditionally."""
    _make_run(store, "D", datetime.now(timezone.utc) - timedelta(minutes=5))
    store.supersede_scan("D", owner=OWNER)

    _make_run(store, "D", datetime.now(timezone.utc), status="running")   # the late claim

    assert store.get_scan("D", owner=OWNER)["run"]["status"] == "superseded", (
        "a late worker claim promoted a superseded run back to 'running'")


def test_an_ordinary_run_still_finalizes_normally(store):
    """The guard must not break the path it sits on — this is the invariant, not the bite."""
    _make_run(store, "E", datetime.now(timezone.utc) - timedelta(minutes=2))
    store.finalize_scan_run("E", _iso(datetime.now(timezone.utc)))
    run = store.get_scan("E", owner=OWNER)["run"]
    assert run["status"] == "done" and run["completed_at"]


def test_a_retry_of_the_same_job_still_resets_status(store):
    """handlers.py relies on init_scan_run resetting a 'failed' run to 'running' on a re-attempt
    ("a between-attempts marker, not a terminal one"). That must keep working."""
    _make_run(store, "F", datetime.now(timezone.utc) - timedelta(minutes=2))
    store.set_scan_status("F", "failed")
    assert store.get_scan("F", owner=OWNER)["run"]["status"] == "failed"

    _make_run(store, "F", datetime.now(timezone.utc), status="running")   # the retry

    assert store.get_scan("F", owner=OWNER)["run"]["status"] == "running", (
        "the resurrection guard also blocked a legitimate retry — too broad")
