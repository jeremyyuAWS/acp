"""_scan_discover's _listing_progress callback (api/handlers.py) must set the job's live 'phase'
to 'discovering', not just 'files_found' — found live 2026-08-26 from a user screenshot showing
the Discover checklist holding at "Connected to source" with zero live detail through the entire
listing/metadata/classification window, then jumping straight to "Applying lifecycle rules" the
instant _list() returned.

Root cause: frontend/src/queuedProgress.js only trusts the durable path's live job state at all
once job.phase is truthy and not 'queued' — `_listing_progress` was updating files_found every
tick without ever setting phase, so every one of those ticks was silently discarded, and the
checklist fell back to inferring phase from scan_runs.files (0 vs nonzero) — a signal that cannot
distinguish listing from metadata from classification, and flips straight from "nothing listed"
to "some files done" (which maps to the SAME displayed step as 'lifecycle') the moment _list()
returns.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def test_listing_progress_sets_phase_to_discovering(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    job_id = "j-listing-phase"
    core.JOBS[job_id] = {"phase": "queued"}
    seen = []

    def _list_stub(*a, **k):
        cb = k.get("progress_cb")
        assert cb is not None, "progress_cb must be threaded through to _list"
        cb(3)
        # Snapshot right after the tick — before _scan_discover moves on to later phases,
        # which would otherwise overwrite 'phase' and hide the bug this test exists to catch.
        seen.append(dict(core.JOBS[job_id]))
        return []

    monkeypatch.setattr(scanner, "_list", _list_stub)

    handlers._scan_discover(
        {"scan_id": "sd-listing-phase", "source": "local", "user": "test@example.com"},
        {"scan_id": "sd-listing-phase", "id": job_id},
    )

    assert seen, "progress_cb (_listing_progress) was never invoked"
    assert seen[0]["phase"] == "discovering"
    assert seen[0]["files_found"] == 3


def test_listing_progress_tick_survives_multiple_calls(isolated_store, monkeypatch):
    """The count updates live across several ticks, each still carrying phase='discovering' —
    not just set once and then silently dropped on subsequent ticks."""
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    job_id = "j-listing-phase-2"
    core.JOBS[job_id] = {"phase": "queued"}
    seen = []

    def _list_stub(*a, **k):
        cb = k.get("progress_cb")
        for n in (10, 25, 60):
            cb(n)
            seen.append(dict(core.JOBS[job_id]))
        return []

    monkeypatch.setattr(scanner, "_list", _list_stub)

    handlers._scan_discover(
        {"scan_id": "sd-listing-phase-2", "source": "local", "user": "test@example.com"},
        {"scan_id": "sd-listing-phase-2", "id": job_id},
    )

    assert [s["files_found"] for s in seen] == [10, 25, 60]
    assert all(s["phase"] == "discovering" for s in seen)


def test_listing_progress_forwards_folder_count_when_given(isolated_store, monkeypatch):
    """The folder-BFS path (_search_folder) reports a live folder count alongside the file
    count; _listing_progress must forward it as folders_found rather than dropping it —
    otherwise DiscoverRunProgress.jsx's 'N files · M folders' KPI never has live folder data
    to show, even though the backend already computed it."""
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    job_id = "j-listing-phase-folders"
    core.JOBS[job_id] = {"phase": "queued"}
    seen = []

    def _list_stub(*a, **k):
        cb = k.get("progress_cb")
        cb(12, 4)  # 12 files found so far, across 4 folders visited
        seen.append(dict(core.JOBS[job_id]))
        return []

    monkeypatch.setattr(scanner, "_list", _list_stub)

    handlers._scan_discover(
        {"scan_id": "sd-listing-phase-folders", "source": "local", "user": "test@example.com"},
        {"scan_id": "sd-listing-phase-folders", "id": job_id},
    )

    assert seen, "progress_cb (_listing_progress) was never invoked"
    assert seen[0]["files_found"] == 12
    assert seen[0]["folders_found"] == 4


def test_listing_progress_omits_folder_count_when_not_given(isolated_store, monkeypatch):
    """The flat Drive-query listing path (_search_drive) has no folder-tree concept and calls
    progress_cb with only a file count. _listing_progress must not invent a folders_found: None
    — the frontend's `foldersFound ?? null` read already treats a missing key correctly, and a
    later tick from a different path must not have its real count clobbered by this one."""
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    job_id = "j-listing-phase-no-folders"
    core.JOBS[job_id] = {"phase": "queued"}
    seen = []

    def _list_stub(*a, **k):
        cb = k.get("progress_cb")
        cb(7)  # no folder count — the _search_drive call shape
        seen.append(dict(core.JOBS[job_id]))
        return []

    monkeypatch.setattr(scanner, "_list", _list_stub)

    handlers._scan_discover(
        {"scan_id": "sd-listing-phase-no-folders", "source": "local", "user": "test@example.com"},
        {"scan_id": "sd-listing-phase-no-folders", "id": job_id},
    )

    assert seen, "progress_cb (_listing_progress) was never invoked"
    assert seen[0]["files_found"] == 7
    assert "folders_found" not in seen[0]
