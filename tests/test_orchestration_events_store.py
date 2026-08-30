"""The operational event stream's store layer — orchestration_events / worker_instances,
PR 1 of a 5-PR delivery plan modeled on ADR 0042's scan_events.

scan_events is the CUSTOMER-FACING scan-lifecycle narrative (always scan-anchored).
orchestration_events is the broader OPERATIONAL layer — job attempts, worker identity and
readiness, Azure capacity transitions, dependency health — including events with NO scan_id at
all. This PR lands the tables and their store methods with NO caller: the emit sites are a later
PR, reviewed on their own. So these tests pin the primitives' contract rather than any pipeline
behaviour:

  * (occurred_at, event_id) ordering, including a stable tiebreak on same-timestamp ties —
    decision_log's pattern, not scan_events' per-scan seq (see the schema comment on
    orchestration_events for why that mechanism doesn't apply here).
  * a write can fail without the caller noticing (store outage), but can never write something
    WRONG — append_orchestration_event swallows store failures and returns None, matching
    append_scan_event's contract.
  * a bad `kind` or `error_class` RAISES — a programming error, not a runtime condition.
  * detail_json is capped and truncates with a marker instead of ever emitting invalid JSON.
  * owner_email-scoped reads never leak another tenant's events.
  * worker_instances is a current-state registry: upsert updates in place, never appends.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


# ── append / read-back ────────────────────────────────────────────────────────

def test_append_returns_an_event_id(isolated_store):
    event_id = isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready")
    assert event_id, "a successful append must return a non-empty event_id"


def test_event_reads_back_with_every_field_it_was_written_with(isolated_store):
    isolated_store.append_orchestration_event(
        owner_email="a@x", kind="job.claimed", occurred_at="2026-08-30T12:00:00.000000+00:00",
        scan_id="s1", job_id="j-1", job_type="scan_file", attempt=2, workflow="Assess",
        stage="assessing", severity="info", worker_id="w3", replica_id="r7",
        revision_name="acp--0042", correlation_id="corr-1", provider="azure_openai",
        error_class="timeout", duration_ms=1500, detail={"files_found": 4100})

    (row,) = isolated_store.list_orchestration_events(owner_email="a@x")
    assert row["owner_email"] == "a@x"
    assert row["kind"] == "job.claimed"
    assert row["occurred_at"] == "2026-08-30T12:00:00.000000+00:00"
    assert row["scan_id"] == "s1"
    assert row["job_id"] == "j-1"
    assert row["job_type"] == "scan_file"
    assert row["attempt"] == 2
    assert row["workflow"] == "Assess"
    assert row["stage"] == "assessing"
    assert row["severity"] == "info"
    assert row["worker_id"] == "w3"
    assert row["replica_id"] == "r7"
    assert row["revision_name"] == "acp--0042"
    assert row["correlation_id"] == "corr-1"
    assert row["provider"] == "azure_openai"
    assert row["error_class"] == "timeout"
    assert row["duration_ms"] == 1500
    assert row["detail"] == {"files_found": 4100}, "detail must come back as a dict, not JSON text"
    assert row["schema_version"] == isolated_store._ORCH_EVENT_SCHEMA_VERSION
    assert row["event_id"], "every event carries a stable id"
    assert "detail_json" not in row, "the raw column is replaced by the decoded `detail` key"


def test_scan_id_and_most_fields_are_optional(isolated_store):
    """The whole point of this table vs scan_events: many kinds have no scan at all."""
    event_id = isolated_store.append_orchestration_event(
        owner_email="a@x", kind="capacity.shortage_detected")
    assert event_id
    (row,) = isolated_store.list_orchestration_events(owner_email="a@x")
    assert row["scan_id"] is None
    assert row["job_id"] is None
    assert row["worker_id"] is None


def test_detail_is_none_when_not_supplied(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.starting")
    (row,) = isolated_store.list_orchestration_events(owner_email="a@x")
    assert row["detail"] is None


def test_unserializable_detail_loses_the_detail_not_the_event(isolated_store):
    event_id = isolated_store.append_orchestration_event(
        owner_email="a@x", kind="job.failed", detail={"exc": object()})
    assert event_id, "the event still landed"
    (row,) = isolated_store.list_orchestration_events(owner_email="a@x")
    assert row["kind"] == "job.failed"
    assert row["detail"] is None


# ── size cap / truncation ───────────────────────────────────────────────────────

def test_detail_over_the_cap_truncates_to_valid_json_with_a_marker(isolated_store):
    import json
    big_detail = {"message": "x" * 5000}   # comfortably over _ORCH_DETAIL_MAX_BYTES
    original_size = len(json.dumps(big_detail).encode("utf-8"))

    event_id = isolated_store.append_orchestration_event(
        owner_email="a@x", kind="job.failed", detail=big_detail)
    assert event_id, "an oversized detail must not cost the event"

    (row,) = isolated_store.list_orchestration_events(owner_email="a@x")
    assert row["detail"] == {"truncated": True, "original_size": original_size}, (
        "must drop to the truncation marker, never emit cut-mid-JSON")


def test_detail_at_or_under_the_cap_is_not_truncated(isolated_store):
    small_detail = {"files_found": 4100}
    isolated_store.append_orchestration_event(owner_email="a@x", kind="job.completed", detail=small_detail)
    (row,) = isolated_store.list_orchestration_events(owner_email="a@x")
    assert row["detail"] == small_detail


# ── ordering ──────────────────────────────────────────────────────────────────

def test_reads_back_oldest_first_by_occurred_at(isolated_store):
    for i, kind in enumerate(("worker.starting", "worker.ready", "worker.busy")):
        isolated_store.append_orchestration_event(
            owner_email="a@x", kind=kind,
            occurred_at=f"2026-08-30T12:00:0{i}.000000+00:00")

    rows = isolated_store.list_orchestration_events(owner_email="a@x")
    assert [r["kind"] for r in rows] == ["worker.starting", "worker.ready", "worker.busy"]


def test_same_timestamp_ties_are_ordered_stably_by_event_id(isolated_store):
    """(occurred_at, event_id) — the tiebreak that makes ordering a total order even when two
    events share a wall-clock timestamp (e.g. two writers observing the same instant)."""
    same_ts = "2026-08-30T12:00:00.000000+00:00"
    for kind in ("worker.starting", "worker.ready", "worker.busy"):
        isolated_store.append_orchestration_event(owner_email="a@x", kind=kind, occurred_at=same_ts)

    rows = isolated_store.list_orchestration_events(owner_email="a@x")
    assert len(rows) == 3
    event_ids = [r["event_id"] for r in rows]
    assert event_ids == sorted(event_ids), (
        "same-timestamp rows must come back sorted by event_id — that's the tiebreak")


def test_concurrent_appends_all_land_with_no_shared_identity(isolated_store):
    """orchestration_events has NO per-key monotonic counter to race over (unlike scan_events'
    per-scan seq), so there is nothing here that needs seq's INSERT-time-assignment-and-retry
    dance. event_id is a fresh uuid4 per call, independent of every other writer; ordering comes
    from (occurred_at, event_id), a tuple no two writers can collide on. This test exists to prove
    that claim rather than assert it silently: N threads appending concurrently must all land,
    all get distinct ids, and read back in a consistent, gap-free (occurred_at, event_id) order."""
    threads, returned, errors = [], [], []
    lock = threading.Lock()

    def _append(i):
        try:
            event_id = isolated_store.append_orchestration_event(
                owner_email="a@x", kind="job.retry_started", attempt=i,
                occurred_at="2026-08-30T12:00:00.000000+00:00")   # same instant, on purpose
            with lock:
                returned.append(event_id)
        except Exception as e:                                   # pragma: no cover - diagnostic
            with lock:
                errors.append(e)

    for i in range(12):
        t = threading.Thread(target=_append, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"append_orchestration_event raised under concurrency: {errors}"
    assert len(returned) == 12
    assert all(returned), "no appends were silently dropped"
    assert len(set(returned)) == 12, "two writers must never share an event_id"

    rows = isolated_store.list_orchestration_events(owner_email="a@x", limit=100)
    assert len(rows) == 12
    ids = [r["event_id"] for r in rows]
    assert ids == sorted(ids), "concurrent same-timestamp writes still read back in a stable order"


# ── reads / filters ──────────────────────────────────────────────────────────

def test_owner_scoped_read_excludes_another_owners_events(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready")
    isolated_store.append_orchestration_event(owner_email="b@x", kind="worker.ready")

    rows = isolated_store.list_orchestration_events(owner_email="a@x")
    assert len(rows) == 1
    assert rows[0]["owner_email"] == "a@x"


def test_no_owner_is_a_global_admin_read(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready")
    isolated_store.append_orchestration_event(owner_email="b@x", kind="worker.ready")

    rows = isolated_store.list_orchestration_events()
    assert len(rows) == 2, "omitting owner_email is a global/admin read, matching job_stats' pattern"


def test_scan_id_filter(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="job.claimed", scan_id="s1")
    isolated_store.append_orchestration_event(owner_email="a@x", kind="job.claimed", scan_id="s2")
    rows = isolated_store.list_orchestration_events(scan_id="s1")
    assert len(rows) == 1 and rows[0]["scan_id"] == "s1"


def test_job_id_filter(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="job.claimed", job_id="j1")
    isolated_store.append_orchestration_event(owner_email="a@x", kind="job.claimed", job_id="j2")
    rows = isolated_store.list_orchestration_events(job_id="j1")
    assert len(rows) == 1 and rows[0]["job_id"] == "j1"


def test_worker_id_filter(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready", worker_id="w1")
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready", worker_id="w2")
    rows = isolated_store.list_orchestration_events(worker_id="w1")
    assert len(rows) == 1 and rows[0]["worker_id"] == "w1"


def test_kind_filter(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready")
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.busy")
    rows = isolated_store.list_orchestration_events(kind="worker.busy")
    assert len(rows) == 1 and rows[0]["kind"] == "worker.busy"


def test_after_cursor_returns_only_what_the_caller_missed(isolated_store):
    for i, kind in enumerate(("worker.starting", "worker.ready", "worker.busy", "worker.draining")):
        isolated_store.append_orchestration_event(
            owner_email="a@x", kind=kind, occurred_at=f"2026-08-30T12:00:0{i}.000000+00:00")

    first_page = isolated_store.list_orchestration_events(owner_email="a@x", limit=2)
    assert [r["kind"] for r in first_page] == ["worker.starting", "worker.ready"]
    cursor = (first_page[-1]["occurred_at"], first_page[-1]["event_id"])

    rest = isolated_store.list_orchestration_events(owner_email="a@x", after=cursor)
    assert [r["kind"] for r in rest] == ["worker.busy", "worker.draining"], (
        "after is exclusive — the cursor row itself is not repeated")


def test_after_cursor_does_not_skip_a_same_timestamp_neighbour(isolated_store):
    """The whole reason `after` is a (occurred_at, event_id) tuple and not a bare timestamp:
    a same-timestamp neighbour must never be silently skipped."""
    same_ts = "2026-08-30T12:00:00.000000+00:00"
    ids = []
    for kind in ("worker.starting", "worker.ready", "worker.busy"):
        eid = isolated_store.append_orchestration_event(owner_email="a@x", kind=kind, occurred_at=same_ts)
        ids.append(eid)
    ordered = sorted(ids)

    cursor = (same_ts, ordered[0])
    rest = isolated_store.list_orchestration_events(owner_email="a@x", after=cursor)
    assert [r["event_id"] for r in rest] == ordered[1:], (
        "the two later same-timestamp rows must both come back, in id order")


def test_unknown_filters_read_empty_rather_than_raising(isolated_store):
    assert isolated_store.list_orchestration_events(scan_id="never-existed") == []
    assert isolated_store.list_orchestration_events(owner_email="nobody@x") == []


def test_limit_caps_the_read_to_the_oldest(isolated_store):
    for i in range(5):
        isolated_store.append_orchestration_event(
            owner_email="a@x", kind="job.retry_started",
            occurred_at=f"2026-08-30T12:00:0{i}.000000+00:00")
    rows = isolated_store.list_orchestration_events(owner_email="a@x", limit=2)
    assert len(rows) == 2
    assert rows[0]["occurred_at"] == "2026-08-30T12:00:00.000000+00:00"


# ── contract on failure ────────────────────────────────────────────────────────

def test_unknown_kind_raises_and_writes_nothing(isolated_store):
    with pytest.raises(ValueError, match="unknown orchestration event kind"):
        isolated_store.append_orchestration_event(owner_email="a@x", kind="job.something_invented")
    assert isolated_store.list_orchestration_events(owner_email="a@x") == []


def test_missing_owner_email_raises(isolated_store):
    with pytest.raises(ValueError, match="requires an owner_email"):
        isolated_store.append_orchestration_event(owner_email="", kind="worker.ready")


def test_unknown_error_class_raises_and_writes_nothing(isolated_store):
    with pytest.raises(ValueError, match="unknown error_class"):
        isolated_store.append_orchestration_event(
            owner_email="a@x", kind="job.failed", error_class="not_a_real_class")
    assert isolated_store.list_orchestration_events(owner_email="a@x") == []


def test_every_declared_kind_is_actually_writable(isolated_store):
    """The vocabulary and the write path must not drift apart."""
    for kind in sorted(isolated_store.ORCHESTRATION_EVENT_KINDS):
        event_id = isolated_store.append_orchestration_event(owner_email="a@x", kind=kind)
        assert event_id, f"{kind} was not writable"


def test_every_declared_error_class_is_accepted(isolated_store):
    for ec in sorted(isolated_store.ERROR_CLASS_VOCABULARY):
        event_id = isolated_store.append_orchestration_event(
            owner_email="a@x", kind="job.failed", error_class=ec)
        assert event_id, f"error_class={ec} was rejected"


def test_a_store_failure_on_append_returns_none_and_does_not_raise(isolated_store, monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def _broken():
        raise RuntimeError("database is on fire")
        yield  # pragma: no cover

    monkeypatch.setattr(isolated_store._db, "cursor", _broken)
    assert isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready") is None


def test_a_store_failure_on_read_returns_empty_and_does_not_raise(isolated_store, monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def _broken():
        raise RuntimeError("database is on fire")
        yield  # pragma: no cover

    monkeypatch.setattr(isolated_store._db, "cursor", _broken)
    assert isolated_store.list_orchestration_events(owner_email="a@x") == []


# ── lifetime: reset / delete ──────────────────────────────────────────────────

def _seed_scan_run(st, scan_id: str, owner: str) -> None:
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, completed_at, files) VALUES (%s,%s,%s,%s)",
            (scan_id, owner, "2026-08-30T00:00:00", 1))


def test_delete_scan_removes_that_scans_orchestration_events(isolated_store):
    st = isolated_store
    _seed_scan_run(st, "s1", "a@x")
    _seed_scan_run(st, "s2", "a@x")
    st.append_orchestration_event(owner_email="a@x", kind="job.claimed", scan_id="s1")
    st.append_orchestration_event(owner_email="a@x", kind="job.claimed", scan_id="s2")

    assert st.delete_scan("s1", "a@x") is not None
    assert st.list_orchestration_events(scan_id="s1") == []
    assert len(st.list_orchestration_events(scan_id="s2")) == 1


def test_delete_scan_does_not_touch_scanless_events_for_the_same_owner(isolated_store):
    """A worker-readiness event has no scan_id — deleting one scan must not touch it."""
    st = isolated_store
    _seed_scan_run(st, "s1", "a@x")
    st.append_orchestration_event(owner_email="a@x", kind="job.claimed", scan_id="s1")
    st.append_orchestration_event(owner_email="a@x", kind="worker.ready")   # no scan_id

    st.delete_scan("s1", "a@x")
    remaining = st.list_orchestration_events(owner_email="a@x")
    assert len(remaining) == 1
    assert remaining[0]["kind"] == "worker.ready"


def test_reset_analytics_clears_orchestration_events(isolated_store):
    isolated_store.append_orchestration_event(owner_email="a@x", kind="worker.ready")
    cleared = isolated_store.reset_analytics()
    assert "orchestration_events" in cleared
    assert isolated_store.list_orchestration_events() == []


def test_reset_user_data_clears_the_owners_scan_anchored_events(isolated_store):
    st = isolated_store
    _seed_scan_run(st, "s1", "a@x")
    _seed_scan_run(st, "s2", "b@x")
    st.append_orchestration_event(owner_email="a@x", kind="job.claimed", scan_id="s1")
    st.append_orchestration_event(owner_email="b@x", kind="job.claimed", scan_id="s2")

    st.reset_user_data("a@x")

    assert st.list_orchestration_events(owner_email="a@x") == []
    assert len(st.list_orchestration_events(owner_email="b@x")) == 1, "the other tenant survives"


def test_reset_user_data_also_clears_the_owners_scanless_events(isolated_store):
    """The case _RESET_USER_SCAN_TABLES' scan_id-IN-subquery pass cannot reach on its own —
    reset_user_data's explicit second pass (scoped by owner_email directly) is what this proves."""
    st = isolated_store
    st.append_orchestration_event(owner_email="a@x", kind="worker.ready")          # no scan_id
    st.append_orchestration_event(owner_email="b@x", kind="worker.ready")          # other tenant

    st.reset_user_data("a@x")

    assert st.list_orchestration_events(owner_email="a@x") == []
    assert len(st.list_orchestration_events(owner_email="b@x")) == 1


# ── worker_instances: current-state registry ───────────────────────────────────

def test_upsert_creates_a_new_row(isolated_store):
    isolated_store.upsert_worker_instance("w1", state="starting", concurrency_limit=4)
    (row,) = isolated_store.list_worker_instances()
    assert row["worker_id"] == "w1"
    assert row["state"] == "starting"
    assert row["concurrency_limit"] == 4


def test_upsert_updates_in_place_not_append(isolated_store):
    isolated_store.upsert_worker_instance("w1", state="starting")
    isolated_store.upsert_worker_instance("w1", state="ready", active_job_count=0)

    rows = isolated_store.list_worker_instances()
    assert len(rows) == 1, "a second upsert for the same worker_id must UPDATE, not insert"
    assert rows[0]["state"] == "ready"
    assert rows[0]["active_job_count"] == 0


def test_partial_upsert_does_not_clobber_fields_it_did_not_pass(isolated_store):
    isolated_store.upsert_worker_instance(
        "w1", state="starting", concurrency_limit=4, revision_name="acp--0042")
    isolated_store.upsert_worker_instance("w1", state="ready")   # only touches `state`

    (row,) = isolated_store.list_worker_instances()
    assert row["state"] == "ready"
    assert row["concurrency_limit"] == 4, "an earlier field must survive a later partial upsert"
    assert row["revision_name"] == "acp--0042"


def test_supported_job_types_list_is_json_encoded(isolated_store):
    isolated_store.upsert_worker_instance("w1", supported_job_types=["scan_file", "scan_batch"])
    (row,) = isolated_store.list_worker_instances()
    import json
    assert json.loads(row["supported_job_types"]) == ["scan_file", "scan_batch"]


def test_list_worker_instances_filters_by_state(isolated_store):
    isolated_store.upsert_worker_instance("w1", state="ready")
    isolated_store.upsert_worker_instance("w2", state="draining")
    isolated_store.upsert_worker_instance("w3", state="ready")

    ready = isolated_store.list_worker_instances(state="ready")
    assert {r["worker_id"] for r in ready} == {"w1", "w3"}


def test_upsert_missing_worker_id_raises(isolated_store):
    with pytest.raises(ValueError, match="requires a worker_id"):
        isolated_store.upsert_worker_instance("", state="ready")


def test_upsert_unknown_field_raises(isolated_store):
    with pytest.raises(ValueError, match="unknown worker_instances field"):
        isolated_store.upsert_worker_instance("w1", not_a_real_field="x")


def test_upsert_unknown_state_raises(isolated_store):
    with pytest.raises(ValueError, match="unknown worker state"):
        isolated_store.upsert_worker_instance("w1", state="not_a_real_state")


def test_reset_analytics_clears_worker_instances(isolated_store):
    isolated_store.upsert_worker_instance("w1", state="ready")
    cleared = isolated_store.reset_analytics()
    assert "worker_instances" in cleared
    assert isolated_store.list_worker_instances() == []


def test_reset_user_data_does_not_touch_worker_instances(isolated_store):
    """worker_instances has no owner_email — it isn't scoped to any tenant, so a per-user reset
    must leave it alone. Only the global reset_analytics() clears it (see the test above)."""
    isolated_store.upsert_worker_instance("w1", state="ready")
    isolated_store.reset_user_data("a@x")
    assert len(isolated_store.list_worker_instances()) == 1
