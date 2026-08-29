"""The durable scan-lifecycle event log's store layer (ADR 0042, PR 1 of 4).

This PR lands the table and its two accessors with NO caller — the emit sites are PR 2 and the
read surface is PR 3, and each wants reviewing on its own. So these tests pin the primitive's
contract rather than any pipeline behaviour:

  * seq is per-scan, monotonic, gap-free, and unique EVEN UNDER CONCURRENT WRITERS. That last
    one is the whole reason seq is assigned inside the INSERT instead of read-then-written:
    events for one scan can legitimately come from two writers at once (a reclaimed job's second
    worker — see test_job_completion_race.py), and two events silently sharing a position would
    make the ordering guarantee a lie exactly when it matters most.
  * a write can fail without the caller noticing, but can never write something WRONG — the
    append swallows store failures and returns None, the same contract activity.py holds.
  * a bad `kind` RAISES, because that is a programming error, not a runtime condition.
  * the log dies with the scan it describes (delete_scan / reset), and only then.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


# ── append / read-back ────────────────────────────────────────────────────────

def test_append_returns_seq_1_for_a_scans_first_event(isolated_store):
    seq = isolated_store.append_scan_event("s1", "scan.queued")
    assert seq == 1, "the first event of a scan must be seq=1, not 0 and not None"


def test_event_reads_back_with_every_field_it_was_written_with(isolated_store):
    isolated_store.append_scan_event(
        "s1", "scan.claimed", phase="discovering", job_id="j-1", worker_id="w3",
        attempt=2, detail={"files_found": 4100}, owner_email="a@x",
        occurred_at="2026-08-29T12:00:00+00:00")

    (row,) = isolated_store.list_scan_events("s1")
    assert row["scan_id"] == "s1"
    assert row["seq"] == 1
    assert row["kind"] == "scan.claimed"
    assert row["phase"] == "discovering"
    assert row["job_id"] == "j-1"
    assert row["worker_id"] == "w3"
    assert row["attempt"] == 2
    assert row["owner_email"] == "a@x"
    assert row["occurred_at"] == "2026-08-29T12:00:00+00:00"
    assert row["detail"] == {"files_found": 4100}, "detail must come back as a dict, not JSON text"
    assert row["event_id"], "every event carries a stable id"


def test_detail_is_none_when_not_supplied_rather_than_a_raw_null_string(isolated_store):
    isolated_store.append_scan_event("s1", "scan.queued")
    (row,) = isolated_store.list_scan_events("s1")
    assert row["detail"] is None


def test_unserializable_detail_loses_the_detail_not_the_event(isolated_store):
    """A telemetry payload that can't be JSON-encoded must not cost us the transition itself."""
    seq = isolated_store.append_scan_event("s1", "scan.failed", detail={"exc": object()})
    assert seq == 1, "the event still landed"
    (row,) = isolated_store.list_scan_events("s1")
    assert row["kind"] == "scan.failed"
    assert row["detail"] is None


# ── ordering ──────────────────────────────────────────────────────────────────

def test_seq_increments_per_scan_and_reads_back_oldest_first(isolated_store):
    for kind in ("scan.queued", "scan.claimed", "scan.listing_started", "scan.completed"):
        isolated_store.append_scan_event("s1", kind)

    rows = isolated_store.list_scan_events("s1")
    assert [r["seq"] for r in rows] == [1, 2, 3, 4]
    assert [r["kind"] for r in rows] == [
        "scan.queued", "scan.claimed", "scan.listing_started", "scan.completed"], (
        "list_scan_events is ASCENDING — the consumer is 'what happened', not an audit browse")


def test_seq_is_scoped_per_scan_so_two_runs_do_not_share_a_counter(isolated_store):
    isolated_store.append_scan_event("s1", "scan.queued")
    isolated_store.append_scan_event("s1", "scan.claimed")
    first_of_s2 = isolated_store.append_scan_event("s2", "scan.queued")

    assert first_of_s2 == 1, "a new scan starts its own sequence at 1"
    assert [r["seq"] for r in isolated_store.list_scan_events("s1")] == [1, 2]


def test_concurrent_appends_never_share_a_seq(isolated_store):
    """The reason seq is assigned inside the INSERT rather than read-then-written.

    Two writers computing MAX(seq)+1 independently compute the SAME number; the UNIQUE index
    rejects the loser and append_scan_event retries for the next one.

    MEASURED, not assumed — this exact 12-thread race was run against both designs on a real
    SQLite store before the design was written down:

        shipped (seq inside the INSERT + retry): 12/12 landed, seqs [1..12], no gaps
        naive   (SELECT MAX+1, then INSERT):      2/12 landed, 10 events LOST

    Note WHICH way the naive version fails. It produces no duplicates — the UNIQUE index stops
    those — it silently DROPS ten of twelve events, because a rejected insert with no retry is
    an event that simply never happened. Silent loss in an append-only log is worse than
    duplication: nothing downstream can tell a gap from a scan that genuinely did nothing.
    """
    threads, returned, errors = [], [], []
    lock = threading.Lock()

    def _append(i):
        try:
            seq = isolated_store.append_scan_event("s1", "scan.retrying", attempt=i)
            with lock:
                returned.append(seq)
        except Exception as e:                                   # pragma: no cover - diagnostic
            with lock:
                errors.append(e)

    for i in range(12):
        t = threading.Thread(target=_append, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"append_scan_event raised under concurrency: {errors}"
    landed = [s for s in returned if s is not None]
    assert len(landed) == 12, f"{12 - len(landed)} concurrent appends were dropped: {returned}"
    assert len(set(landed)) == len(landed), f"two writers got the same seq: {sorted(landed)}"

    rows = isolated_store.list_scan_events("s1")
    seqs = [r["seq"] for r in rows]
    assert seqs == list(range(1, 13)), f"seq is not gap-free/unique in the table: {seqs}"
    assert len({r["event_id"] for r in rows}) == 12, "event_ids must be distinct"


def test_returned_seq_belongs_to_the_event_that_was_written(isolated_store):
    """The return value is read back by event_id, not recomputed as MAX(seq) — recomputing
    would report a CONCURRENT writer's seq as this event's."""
    seq = isolated_store.append_scan_event("s1", "scan.queued")
    isolated_store.append_scan_event("s1", "scan.claimed")     # someone else appends after us
    match = [r for r in isolated_store.list_scan_events("s1") if r["seq"] == seq]
    assert [r["kind"] for r in match] == ["scan.queued"]


# ── reads ─────────────────────────────────────────────────────────────────────

def test_unknown_scan_reads_empty_rather_than_raising(isolated_store):
    assert isolated_store.list_scan_events("never-existed") == []


def test_after_seq_returns_only_what_the_caller_missed(isolated_store):
    for kind in ("scan.queued", "scan.claimed", "scan.discovered", "scan.completed"):
        isolated_store.append_scan_event("s1", kind)

    missed = isolated_store.list_scan_events("s1", after_seq=2)
    assert [r["seq"] for r in missed] == [3, 4], "after_seq is exclusive — 2 was already seen"
    assert isolated_store.list_scan_events("s1", after_seq=4) == [], "caught up reads empty"


def test_owner_filter_excludes_another_owners_events(isolated_store):
    isolated_store.append_scan_event("s1", "scan.queued", owner_email="a@x")
    isolated_store.append_scan_event("s1", "scan.claimed", owner_email="b@x")

    assert [r["kind"] for r in isolated_store.list_scan_events("s1", owner="a@x")] == ["scan.queued"]


def test_owner_filter_hides_rows_written_before_an_owner_was_known(isolated_store):
    """Documented in list_scan_events: owner_email is NULL until the owner is known, and those
    rows do NOT come back from an owner-scoped read. A route must gate on get_scan(owner=...)
    first — this filter is not the access check, and a test should say so out loud."""
    isolated_store.append_scan_event("s1", "scan.queued")                    # no owner yet
    isolated_store.append_scan_event("s1", "scan.claimed", owner_email="a@x")

    assert len(isolated_store.list_scan_events("s1")) == 2
    assert [r["kind"] for r in isolated_store.list_scan_events("s1", owner="a@x")] == ["scan.claimed"]


def test_limit_caps_the_read(isolated_store):
    for _ in range(5):
        isolated_store.append_scan_event("s1", "scan.retrying")
    rows = isolated_store.list_scan_events("s1", limit=2)
    assert [r["seq"] for r in rows] == [1, 2], "the limit takes the OLDEST, matching ORDER BY seq"


# ── the contract on failure ───────────────────────────────────────────────────

def test_unknown_kind_raises_rather_than_writing_a_row_nothing_can_render(isolated_store):
    with pytest.raises(ValueError, match="unknown scan event kind"):
        isolated_store.append_scan_event("s1", "scan.something_invented")
    assert isolated_store.list_scan_events("s1") == []


def test_missing_scan_id_raises(isolated_store):
    with pytest.raises(ValueError, match="requires a scan_id"):
        isolated_store.append_scan_event("", "scan.queued")


def test_every_declared_kind_is_actually_writable(isolated_store):
    """The vocabulary and the write path must not drift apart — a kind declared but rejected
    would only surface at the call site that first tried to emit it."""
    for i, kind in enumerate(sorted(isolated_store.SCAN_EVENT_KINDS), start=1):
        assert isolated_store.append_scan_event("s1", kind) == i, f"{kind} was not writable"


def test_a_store_failure_returns_none_and_does_not_raise(isolated_store, monkeypatch):
    """An append must never be able to fail the work it describes (activity.py's contract).
    PR 2's call sites wrap this too, but the guarantee belongs at the write."""
    import contextlib

    @contextlib.contextmanager
    def _broken():
        raise RuntimeError("database is on fire")
        yield  # pragma: no cover

    monkeypatch.setattr(isolated_store._db, "cursor", _broken)
    assert isolated_store.append_scan_event("s1", "scan.queued") is None


def test_a_store_failure_on_read_returns_empty_and_does_not_raise(isolated_store, monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def _broken():
        raise RuntimeError("database is on fire")
        yield  # pragma: no cover

    monkeypatch.setattr(isolated_store._db, "cursor", _broken)
    assert isolated_store.list_scan_events("s1") == []


# ── lifetime: the log dies with the scan, and only then ───────────────────────

def _seed_scan_run(st, scan_id: str, owner: str) -> None:
    """A minimal scan_runs row — delete_scan/reset_user_data both gate on ownership there.
    Same shape test_delete_scan.py's own `_seed_scan` uses."""
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, completed_at, files) VALUES (%s,%s,%s,%s)",
            (scan_id, owner, "2026-08-29T00:00:00", 1))


def test_delete_scan_removes_that_scans_events(isolated_store):
    st = isolated_store
    _seed_scan_run(st, "s1", "a@x")
    _seed_scan_run(st, "s2", "a@x")
    st.append_scan_event("s1", "scan.queued", owner_email="a@x")
    st.append_scan_event("s2", "scan.queued", owner_email="a@x")

    assert st.delete_scan("s1", "a@x") is not None
    assert st.list_scan_events("s1") == [], "deleting a scan must take its lifecycle log with it"
    assert len(st.list_scan_events("s2")) == 1, "another scan's log is untouched"


def test_reset_analytics_clears_the_event_log(isolated_store):
    isolated_store.append_scan_event("s1", "scan.queued")
    cleared = isolated_store.reset_analytics()
    assert "scan_events" in cleared
    assert isolated_store.list_scan_events("s1") == []


def test_reset_user_data_clears_the_owners_scan_events(isolated_store):
    st = isolated_store
    _seed_scan_run(st, "s1", "a@x")
    _seed_scan_run(st, "s2", "b@x")
    st.append_scan_event("s1", "scan.queued", owner_email="a@x")
    st.append_scan_event("s2", "scan.queued", owner_email="b@x")

    st.reset_user_data("a@x")

    assert st.list_scan_events("s1") == []
    assert len(st.list_scan_events("s2")) == 1, "the other tenant's log survives"
