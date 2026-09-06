"""Retention for the worker registry.

`worker_instances` is written on every heartbeat by worker_telemetry.WorkerInstanceReporter and
was pruned by NOTHING, so a row accumulated per process, per replica, per revision. On 2026-09-06
production reported 1000 rows to the Live Operations drawer -- every one stale, every one
"0 of 0 slots busy", all from revisions retired the day before.

The panel now counts stale rows instead of listing them, which fixed the reading. This fixes the
table.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api import sweeper


NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def _beat(store, worker_id, ago_seconds, **fields):
    store.upsert_worker_instance(
        worker_id,
        last_heartbeat_at=(NOW - timedelta(seconds=ago_seconds)).isoformat(),
        replica_id=fields.pop("replica_id", f"rep-{worker_id}"),
        state=fields.pop("state", "ready"), **fields)


def _ids(store):
    return sorted(row["worker_id"] for row in store.list_worker_instances())


# -- the age ceiling ---------------------------------------------------------------------------

def test_drops_rows_past_the_retention_window_and_keeps_the_rest(isolated_store):
    _beat(isolated_store, "live", 5)
    _beat(isolated_store, "recent", 3600)          # an hour old: stale, but yesterday's evidence
    _beat(isolated_store, "yesterday", 25 * 3600)  # past the window
    _beat(isolated_store, "ancient", 400 * 3600)

    removed = isolated_store.prune_worker_instances(now=NOW)

    assert removed == 2
    assert _ids(isolated_store) == ["live", "recent"]


def test_keeps_a_stale_row_inside_the_window_because_it_is_the_signal(isolated_store):
    """A replica that stopped reporting four hours ago is what an operator reads the morning
    after a bad rollout. Pruning at the freshness threshold would erase the evidence at exactly
    the moment it becomes interesting."""
    _beat(isolated_store, "stopped-reporting", 4 * 3600)
    assert isolated_store.prune_worker_instances(now=NOW) == 0
    assert _ids(isolated_store) == ["stopped-reporting"]


def test_a_row_that_never_reported_is_prunable(isolated_store):
    # `NULL < %s` is NULL, not true, so a bare comparison keeps these forever -- the one class of
    # row most certainly dead.
    isolated_store.upsert_worker_instance("never-beat", replica_id="rep-x", state="starting")
    assert isolated_store.prune_worker_instances(now=NOW) == 1
    assert _ids(isolated_store) == []


# -- the freshness floor -----------------------------------------------------------------------

def test_no_rule_can_delete_a_live_row(isolated_store):
    """A ceiling that could evict live rows would UNDER-REPORT capacity, which is a worse failure
    than a large table."""
    for i in range(20):
        _beat(isolated_store, f"live-{i:02d}", 5)

    # Both rules, at their most aggressive: everything is "past" a zero-hour window, and the row
    # ceiling is below the number of live rows.
    removed = isolated_store.prune_worker_instances(max_age_hours=0, max_rows=1, now=NOW)
    assert removed == 0
    assert len(_ids(isolated_store)) == 20


# -- the row ceiling ---------------------------------------------------------------------------

def test_the_row_ceiling_catches_what_age_cannot(isolated_store):
    """A rollout storm mints rows faster than the age window retires them."""
    for i in range(30):
        # All inside the 24h window, all outside the freshness floor.
        _beat(isolated_store, f"burst-{i:02d}", 3600 + i * 60)

    removed = isolated_store.prune_worker_instances(max_rows=10, now=NOW)

    assert removed == 20
    assert len(_ids(isolated_store)) == 10


def test_the_ceiling_evicts_the_oldest_first(isolated_store):
    _beat(isolated_store, "oldest", 20 * 3600)
    _beat(isolated_store, "middle", 10 * 3600)
    _beat(isolated_store, "newest", 2 * 3600)

    isolated_store.prune_worker_instances(max_rows=1, now=NOW)

    assert _ids(isolated_store) == ["newest"]


def test_a_table_under_the_ceiling_is_left_alone(isolated_store):
    _beat(isolated_store, "a", 3600)
    _beat(isolated_store, "b", 7200)
    assert isolated_store.prune_worker_instances(max_rows=10, now=NOW) == 0
    assert _ids(isolated_store) == ["a", "b"]


# -- housekeeping never breaks the sweep -------------------------------------------------------

def test_a_failing_prune_returns_rather_than_raising(monkeypatch, isolated_store):
    """The sweep that runs this also reclaims expired job leases.

    An exception here would stop that, so a table left large is the correct failure and a raised
    exception is not.
    """
    class Boom:
        def cursor(self):
            raise RuntimeError("database gone")

    monkeypatch.setattr(isolated_store, "_db", Boom())
    assert isolated_store.prune_worker_instances(now=NOW) == 0


# -- the sweeper runs it -----------------------------------------------------------------------

class _SweepStore:
    """Only what run_sweep touches."""

    def __init__(self):
        self.calls = []

    def reclaim_stuck_jobs(self, *a, **kw): return 0
    def sweep_exhausted_jobs(self, *a, **kw): return 0
    def sweep_orphaned_scans(self, *a, **kw): return 0
    def rescue_unfinalized_scans(self, *a, **kw): return 0
    def prune_scan_events(self, *a, **kw): return 0

    def prune_worker_instances(self, **kw):
        self.calls.append(kw)
        return 3


@pytest.fixture(autouse=True)
def _reset_sweep_clocks():
    sweeper._last_worker_prune = 0.0
    sweeper._last_event_prune = 0.0
    yield
    sweeper._last_worker_prune = 0.0
    sweeper._last_event_prune = 0.0


def test_the_sweeper_applies_worker_retention_and_reports_it():
    store = _SweepStore()
    result = sweeper.run_sweep(store, worker_prune_interval_seconds=0)
    assert result["workers_pruned"] == 3
    assert store.calls == [{"max_age_hours": 24}]


def test_the_sweeper_does_not_prune_on_every_tick():
    # The policy's finest grain is 24 hours; a per-tick DELETE would spend writes proving nothing
    # has aged out yet.
    #
    # The baseline is set EXPLICITLY rather than left at 0.0. time.monotonic() is time since boot,
    # and on a freshly started host it is a small number -- 203 seconds in the container this was
    # written in -- so `now - 0.0 >= 3600` is false and the first tick would not prune at all. The
    # test would then pass for the wrong reason: zero calls, not one.
    import time

    store = _SweepStore()
    sweeper._last_worker_prune = time.monotonic() - 3601
    sweeper.run_sweep(store, worker_prune_interval_seconds=3600)
    sweeper.run_sweep(store, worker_prune_interval_seconds=3600)
    assert len(store.calls) == 1


def test_a_store_without_the_method_does_not_break_the_sweep():
    # Mixed-version rollout: the sweeper can be newer than the store it is handed.
    class Older(_SweepStore):
        prune_worker_instances = None

    result = sweeper.run_sweep(Older(), worker_prune_interval_seconds=0)
    assert result["workers_pruned"] == 0
    assert result["reclaimed"] == 0
