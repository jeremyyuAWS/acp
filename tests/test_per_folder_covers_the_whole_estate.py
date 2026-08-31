"""PROBE — does per-folder fan-out actually cover everything the discovery walk found?

Written before turning ACP_PER_FOLDER_SCAN_JOBS on in production, because the flag has never run
there and the mode's existing tests assert that the fan-out HAPPENED, not that the estate is
covered by it. test_per_folder_scan_jobs.py::test_discover_emits_scan_folder_jobs stubs `_list`
to return three documents and `_list_top_level_folders` to return three folders, then asserts
three scan_folder jobs exist. It never checks that those three documents reach any job.

THE SHAPE OF THE WORRY. In _scan_discover, the per-folder branch:

    folders = _list_top_level_folders(source, effective_folder, toks)
    if folders:
        core.store.set_total_folders(scan_id, len(folders))
        for f in folders: ...enqueue scan_folder...
        return                      # <- _enqueue_analysis(norm) never runs

`items`/`norm` is the inventory the walk just built — every file, at every depth. The branch
discards it and instead enqueues one job per IMMEDIATE SUBFOLDER, each of which re-lists its own
subtree. A file sitting directly in the scope root is inside no immediate subfolder, so it is in
no scan_folder job.

If that is right, two things follow, and the second is worse:
  1. those files are never analysed;
  2. finalization is gated on completed_folders >= total_folders, which knows nothing about
     them — so the run reaches a terminal state and reports success over an estate it did not
     fully read.

That is the exact staging criterion this work is meant to satisfy ("an incomplete scan never
appears complete"), so it has to be measured before the flag moves, not after.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def _jobs(store, scan_id):
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT type, payload FROM jobs WHERE scan_id=%s", (scan_id,))
        return store._db.fetchall(cur) or []


def _every_named_file(store, scan_id):
    """Every filename any job in this scan is carrying, whatever job type holds it."""
    import json
    names = set()
    for row in _jobs(store, scan_id):
        payload = row.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        if payload.get("file"):
            names.add(payload["file"])
        for it in (payload.get("items") or []):
            if isinstance(it, dict) and it.get("file"):
                names.add(it["file"])
    return names


@pytest.fixture()
def env(monkeypatch):
    """A discover job in per-folder mode over an estate with a file at the ROOT and one subfolder."""
    import store as store_mod
    import core
    import handlers
    import scanner
    import worker

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "pf-cover.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)
    monkeypatch.setenv("ACP_PER_FOLDER_SCAN_JOBS", "1")
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "0")

    sid = "s-cover"
    core.register_scan_tokens(sid, drive="dummy-token")

    # The walk finds two documents: one directly in the scope root, one inside "Legal".
    ITEMS = [
        {"name": "root-contract.pdf", "id": "id-root", "mime": None},
        {"name": "Legal/policy.docx", "id": "id-legal", "mime": None},
    ]
    monkeypatch.setattr(scanner, "_drive_service", lambda tok: None)
    monkeypatch.setattr(scanner, "_list", lambda *a, **kw: ITEMS)

    # Only ONE immediate subfolder exists. root-contract.pdf is in no subfolder at all.
    monkeypatch.setattr(handlers, "_list_top_level_folders",
                        lambda source, scope_folder, toks: [{"folder_id": "fLegal", "name": "Legal"}])
    # And that folder, listed on its own, contains only its own file.
    monkeypatch.setattr(handlers, "_list_folder_files",
                        lambda source, folder_id, toks: [
                            {"name": "Legal/policy.docx", "id": "id-legal", "mime": None}])

    jid = st.enqueue_job("scan_discover", {"source": "drive", "scan_id": sid, "ai": True},
                         scan_id=sid)
    w = worker.JobWorker(st, worker_id="w-cover")
    w.run_once()
    assert st.get_job(jid)["status"] == "done"
    return st, sid


def test_a_file_at_the_scope_root_is_not_dropped_by_the_fan_out(env):
    """THE probe. The discovery walk found root-contract.pdf; per-folder fan-out must not lose
    it just because it lives in no subfolder."""
    st, sid = env
    named = _every_named_file(st, sid)
    assert "root-contract.pdf" in named, (
        "the per-folder fan-out dropped a file the discovery walk had already found: it sits "
        f"directly in the scope root, so it is inside no immediate subfolder and therefore in "
        f"no scan_folder job. Jobs carry only: {sorted(named)}")


def test_the_run_cannot_finalize_while_part_of_the_estate_is_unprocessed(env):
    """The worse half. Finalization is gated on completed_folders >= total_folders, which counts
    folders and knows nothing about a root-level file — so a run can reach a terminal state and
    report success over an estate it never fully read."""
    st, sid = env
    # Drive every folder job to completion, as a healthy worker tier would.
    _done, total = None, None
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT total_folders FROM scan_runs WHERE id=%s", (sid,))
        total = (st._db.fetchone(cur) or {}).get("total_folders") or 0
    for _ in range(total):
        st.increment_completed_folders(sid)

    named = _every_named_file(st, sid)
    unprocessed = {"root-contract.pdf"} - named
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT completed_folders, total_folders FROM scan_runs WHERE id=%s",
                       (sid,))
        row = st._db.fetchone(cur) or {}
    finalisable = (row.get("completed_folders") or 0) >= (row.get("total_folders") or 0)

    assert not (finalisable and unprocessed), (
        f"the run is ready to finalize with {sorted(unprocessed)} never enqueued anywhere — "
        "an incomplete scan that will report as complete")
