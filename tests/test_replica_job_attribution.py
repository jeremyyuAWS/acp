"""Which replica is running which job, read from `locked_by`.

Live Operations reported this as impossible — liveOpsDrawer.js said "ACP does not record which
replica ran a job — the registry that would carry it has no writer". That was true of the
worker_instances registry when the sentence was written, and it stopped being true of
`locked_by` on 2026-09-05, when core.worker_process_instance_id started prefixing the Container
Apps replica name (api/core.py:1664-1671). These tests pin the parse, the aggregation and the
refusals, because the failure mode of getting this wrong is not an error — it is a plausible
replica name that nothing runs on.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api import store as store_module
from api.store import parse_worker_id


def _now():
    return datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _DB:
    """Just enough of the store's db shim to exercise the aggregation without Postgres."""

    def __init__(self, rows, *, raises=False):
        self.rows = rows
        self.raises = raises
        self.sql = None

    def cursor(self):
        return _Cursor(self.rows)

    def execute(self, cur, sql, params=()):
        if self.raises:
            raise RuntimeError("store unavailable")
        self.sql = sql

    def fetchall(self, cur):
        return self.rows


class _Store:
    running_jobs_by_replica = store_module.Store.running_jobs_by_replica

    def __init__(self, rows, *, raises=False):
        self._db = _DB(rows, raises=raises)


def _job(locked_by, kind="assess_file", claimed_at=None):
    return {"locked_by": locked_by, "type": kind, "claimed_at": claimed_at}


# ── the parse ────────────────────────────────────────────────────────────────────────────────

def test_parses_the_production_worker_id_shape():
    assert parse_worker_id("assess:acp-assess--0000517-5f9d8:1a2b3c4d:w3") == (
        "assess", "acp-assess--0000517-5f9d8", "1a2b3c4d")


@pytest.mark.parametrize("value", [
    "w0",               # the pre-2026-09-05 per-process sequence: every replica minted "w0"
    "w1",
    "worker-1a2b3c4d",  # JobWorker's own default when no worker_id is passed
    "assess:replica:proc",       # three fields, not four
    "assess:replica:proc:w1:x",  # five
    "assess::proc:w1",           # empty replica
    "",
    None,
    12345,
])
def test_refuses_every_shape_that_does_not_name_a_replica(value):
    # Coercing any of these would invent a replica. "w0" is the dangerous one: it parses as a
    # perfectly plausible name and would report a ten-replica fleet as a single host.
    assert parse_worker_id(value) is None


# ── the aggregation ──────────────────────────────────────────────────────────────────────────

def test_groups_running_jobs_by_replica_with_types_and_oldest_claim():
    now = _now()
    rows = [
        _job("assess:rep-a:p1:w0", "assess_file", (now - timedelta(seconds=30)).isoformat()),
        _job("assess:rep-a:p1:w1", "assess_file", (now - timedelta(seconds=900)).isoformat()),
        _job("assess:rep-a:p2:w0", "extract_text", (now - timedelta(seconds=10)).isoformat()),
        _job("discovery:rep-b:p9:w0", "discover_folder", (now - timedelta(seconds=5)).isoformat()),
    ]
    answer = _Store(rows).running_jobs_by_replica(now=now)

    assert answer["available"] is True
    assert answer["attributed"] == 4
    assert answer["unattributed"] == 0
    # Busiest replica first, so the drawer's first row is the one an operator cares about.
    assert [r["replica_id"] for r in answer["replicas"]] == ["rep-a", "rep-b"]

    busiest = answer["replicas"][0]
    assert busiest["running"] == 3
    assert busiest["roles"] == ["assess"]
    # Two distinct processes on that replica, reported as a count rather than as ids.
    assert busiest["processes"] == 2
    assert busiest["job_types"] == {"assess_file": 2, "extract_text": 1}
    # The OLDEST claim on the replica, which is the one that would be stuck.
    assert 890 <= busiest["oldest_claim_age_s"] <= 910


def test_counts_unparseable_worker_ids_instead_of_naming_a_replica():
    rows = [
        _job("assess:rep-a:p1:w0"),
        _job("w0"),
        _job("worker-deadbeef"),
        _job(None),
    ]
    answer = _Store(rows).running_jobs_by_replica()

    assert answer["attributed"] == 1
    assert answer["unattributed"] == 3
    assert [r["replica_id"] for r in answer["replicas"]] == ["rep-a"]
    assert answer["replicas"][0]["running"] == 1


def test_a_row_with_no_claim_timestamp_contributes_no_age():
    # Rows written before schema v16 have no `claimed_at`. None is the honest answer; 0 would
    # read as "claimed this instant", which is the opposite of what a pre-v16 row means.
    answer = _Store([_job("assess:rep-a:p1:w0", claimed_at=None)]).running_jobs_by_replica()
    assert answer["replicas"][0]["oldest_claim_age_s"] is None
    assert answer["replicas"][0]["running"] == 1


def test_reads_only_running_jobs_and_only_non_sensitive_columns():
    store = _Store([])
    store.running_jobs_by_replica()
    sql = store._db.sql
    assert "status='running'" in sql
    # No payload, no owner, no error text: this lands on a live screen and a job's payload names
    # a customer document.
    for forbidden in ("payload", "owner", "last_error", "scan_id"):
        assert forbidden not in sql


def test_an_unreadable_store_is_unavailable_not_an_empty_fleet():
    answer = _Store([], raises=True).running_jobs_by_replica()
    assert answer["available"] is False
    assert answer["replicas"] == []
    # None, not 0 — nothing was measured, so there is no count to report.
    assert answer["attributed"] is None and answer["unattributed"] is None
    assert "unavailable" in answer["reason"].lower()


# ── the snapshot wiring ──────────────────────────────────────────────────────────────────────

class _ActivityStore:
    """The minimum an activity snapshot needs, plus the attribution method under test."""

    def __init__(self, attribution=None, raises=False):
        self._attribution = attribution
        self._raises = raises

    def worker_tier_status(self):
        return {"alive": True, "pool_size": 4}

    def worker_roles_status(self):
        return {"assess": {"alive": True, "pool_size": 2, "age_s": 1, "version": "v25"}}

    def job_stats(self, owner=None):
        return {"done": 0}

    def admin_live_activity(self):
        return []

    def running_jobs_by_replica(self):
        if self._raises:
            raise RuntimeError("boom")
        return self._attribution


def _snapshot(monkeypatch, store):
    from api.routes import system
    monkeypatch.setattr(system.core, "store", store)
    return system._admin_activity_snapshot()["summary"]


def test_the_snapshot_carries_per_replica_job_attribution(monkeypatch):
    block = {"available": True, "attributed": 2, "unattributed": 0, "reason": None,
             "replicas": [{"replica_id": "rep-a", "roles": ["assess"], "running": 2,
                           "processes": 1, "job_types": {"assess_file": 2},
                           "oldest_claim_age_s": 11}]}
    summary = _snapshot(monkeypatch, _ActivityStore(block))
    assert summary["job_attribution"] == block
    # Kept apart from the slot-capacity block: they answer different questions and can honestly
    # disagree, so merging them would make one of the two wrong.
    assert "available" in summary["worker_instance_attribution"]
    assert summary["worker_instance_attribution"] is not summary["job_attribution"]


def test_a_store_without_the_method_reads_as_unavailable_not_as_an_idle_fleet(monkeypatch):
    class Older(_ActivityStore):
        """A store from before this method existed — the mixed-version rollout case."""
        running_jobs_by_replica = None

    summary = _snapshot(monkeypatch, Older())
    assert summary["job_attribution"]["available"] is False
    assert summary["job_attribution"]["replicas"] == []
    assert "does not report" in summary["job_attribution"]["reason"]


def test_a_raising_store_does_not_take_the_whole_snapshot_down(monkeypatch):
    # The activity stream is the Live Operations screen's only source; one optional block failing
    # must not blank the map.
    summary = _snapshot(monkeypatch, _ActivityStore(raises=True))
    assert summary["job_attribution"]["available"] is False
    assert summary["running"] is not None


# ── against a real store ─────────────────────────────────────────────────────────────────────

def test_a_real_claim_places_its_job_on_the_replica_that_took_it(isolated_store, monkeypatch):
    """End-to-end through claim_job, not through a fake row.

    The fakes above pin the aggregation; this pins that the string `claim_job` actually writes is
    the string `parse_worker_id` actually reads. Those are set in different modules (core mints
    it, store parses it) and nothing but a test that spans both would notice them drifting apart.
    """
    isolated_store.save_scan({
        "_scan_id": "scan-attr-1", "owner": "ops@example.org", "source": "drive",
        "started_at": "2026-09-06T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    })
    isolated_store.enqueue_job("scan_file", {"file": "Report.docx"}, scan_id="scan-attr-1")

    import api.core as core
    monkeypatch.setenv("CONTAINER_APP_REPLICA_NAME", "acp-assess--0000517-xyz9")
    monkeypatch.setenv("ACP_WORKER_ROLE", "assess")
    import joblog
    monkeypatch.setattr(joblog, "REPLICA", "acp-assess--0000517-xyz9")
    worker_id = f"{core.worker_process_instance_id()}:w0"
    assert isolated_store.claim_job(worker_id) is not None

    answer = isolated_store.running_jobs_by_replica()
    assert answer["available"] is True
    assert answer["attributed"] == 1
    assert answer["unattributed"] == 0
    assert [row["replica_id"] for row in answer["replicas"]] == ["acp-assess--0000517-xyz9"]
    assert answer["replicas"][0]["roles"] == ["assess"]
    assert answer["replicas"][0]["job_types"] == {"scan_file": 1}
    # claimed_at is written by claim_job (schema v16), so the age is real, not None.
    assert answer["replicas"][0]["oldest_claim_age_s"] is not None
