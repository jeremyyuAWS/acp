"""_scan_discover (the durable, queue=true handler) must write the scan_id -> job_id mapping
that GET /scans/{scan_id}/discover/stream depends on to find its job's live Redis state.

Found live 2026-08-28: core.get_job_id_for_scan() reads ONLY the scan_to_job:{scan_id} mapping
(Redis, or the per-process _SCAN_JOB_MAP fallback) — it has no fallback to the jobs table's own
scan_id column. That mapping is written by core.set_job/update_job whenever a patch includes a
"scan_id" key (test_job_state_cross_replica.py pins that mechanism). But no call anywhere inside
_scan_discover's body ever included "scan_id" in an update_job patch, so the mapping was NEVER
populated on the durable path — every queue=true scan's SSE stream fell through to the 4-miss
giveup path (~1s) and degraded straight to the Postgres-checkpoint fallback frame, never actually
going live, regardless of whether Redis itself was healthy.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def test_scan_discover_writes_the_scan_to_job_mapping(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    job_id = "j-mapping-durable"
    scan_id = "sd-mapping-durable"
    core.JOBS[job_id] = {"phase": "queued"}

    # Before the handler runs, the mapping must not already exist for this scan_id.
    assert core.get_job_id_for_scan(scan_id) is None

    monkeypatch.setattr(scanner, "_list", lambda *a, **k: [])

    handlers._scan_discover(
        {"scan_id": scan_id, "source": "local", "user": "test@example.com"},
        {"scan_id": scan_id, "id": job_id},
    )

    # The SSE stream (core.get_job_id_for_scan) must now be able to find this job by scan_id —
    # this is what makes GET /scans/{scan_id}/discover/stream able to live-tail the job at all.
    assert core.get_job_id_for_scan(scan_id) == job_id


def test_scan_discover_writes_the_mapping_before_listing_starts(isolated_store, monkeypatch):
    """The mapping must be written EARLY — before the (potentially slow) source listing — so a
    client opening the SSE stream right after the enqueue response can find the job immediately,
    not only once discovery has already finished."""
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    job_id = "j-mapping-early"
    scan_id = "sd-mapping-early"
    core.JOBS[job_id] = {"phase": "queued"}

    seen_mapping_during_listing = {}

    def _list_stub(*a, **k):
        # Snapshot whether the mapping is already resolvable WHILE listing is still in progress —
        # a mapping written only after _scan_discover returns would show None here.
        seen_mapping_during_listing["value"] = core.get_job_id_for_scan(scan_id)
        return []

    monkeypatch.setattr(scanner, "_list", _list_stub)

    handlers._scan_discover(
        {"scan_id": scan_id, "source": "local", "user": "test@example.com"},
        {"scan_id": scan_id, "id": job_id},
    )

    assert seen_mapping_during_listing.get("value") == job_id


def test_scan_discover_skips_the_mapping_write_when_job_has_no_id(isolated_store, monkeypatch):
    """Defensive: a malformed job dict with no 'id' must not raise — core.update_job needs a
    job_id to key its write, so this is a no-op guard, not a new failure mode."""
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    scan_id = "sd-mapping-no-jobid"
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: [])

    # Must not raise despite the job dict carrying no "id".
    handlers._scan_discover(
        {"scan_id": scan_id, "source": "local", "user": "test@example.com"},
        {"scan_id": scan_id},
    )

    assert core.get_job_id_for_scan(scan_id) is None
