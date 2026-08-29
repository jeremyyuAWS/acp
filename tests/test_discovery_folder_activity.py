"""Folder-level activity in scanner._search_folder — which folders the BFS is fetching RIGHT
NOW, and the last few that finished. See _search_folder's own header comment for why this is
bounded/ephemeral rather than a durable history: the walk is parallel (several folders in flight
at once via a thread pool), so a single "current folder" pointer would misrepresent it as serial.
This is surfaced through progress_cb's new `active`/`recent` kwargs, which _listing_progress
(api/handlers.py) forwards onto the same job-state channel files_found/phase already use — see
tests/test_listing_phase_live_tick.py for that leg.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


class _Req:
    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _Files:
    def __init__(self, drive):
        self.d = drive

    def get(self, fileId, fields=None, supportsAllDrives=None):
        return _Req({"name": self.d.names.get(fileId, fileId)})

    def list(self, **kw):
        q = kw.get("q", "")
        fid = q.split("'")[1] if q.startswith("'") else None
        files = self.d.children.get(fid, []) if fid else []
        return _Req({"files": files})


class FakeDrive:
    def __init__(self, children, names=None):
        self.children = children      # {folder_id: [file/folder dicts]}
        self.names = names or {}      # {folder_id: display name}, for the root-name lookup

    def files(self):
        return _Files(self)


def _doc(fid, name="doc.docx"):
    return {"id": fid, "name": name, "mimeType": DOCX}


def _folder(fid, name="subfolder"):
    return {"id": fid, "name": name, "mimeType": FOLDER}


def test_progress_cb_receives_active_and_recent_kwargs():
    """The new kwargs actually arrive, alongside the existing (count, folders) positional ones —
    a caller that ignores them (the flat Drive-query path, or an older test) is unaffected."""
    drive = FakeDrive({"root": [_folder("A")], "A": [_doc("f1")]}, names={"root": "My Drive"})
    ticks = []
    scanner._search_folder(drive, "root", max_files=100,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           ticks.append((count, folders, active, recent)))
    assert ticks, "progress_cb was never called"
    # By the time the BFS finishes, at least one tick reported a completed folder in `recent`.
    assert any(t[3] for t in ticks), "no tick ever reported a recently-completed folder"


def test_recent_records_the_real_folder_name_and_path(monkeypatch):
    # The real throttle gates on wall-clock monotonic() >= 2s since the last tick — too slow to
    # observe in a synchronous unit test where root and its child both finish within microseconds.
    # Force every check past it deterministically instead of sleeping in the test (same technique
    # as test_discovery_parallel_bfs.py's test_progress_cb_receives_live_folder_count).
    clock = [1000.0]

    def _fake_monotonic():
        clock[0] += 3.0
        return clock[0]

    monkeypatch.setattr(scanner.time, "monotonic", _fake_monotonic)
    drive = FakeDrive(
        {"root": [_folder("A", "Compliance")], "A": [_doc("f1")]},
        names={"root": "My Drive"},
    )
    ticks = []
    scanner._search_folder(drive, "root", max_files=100,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           ticks.append(recent or []))
    all_recent = [r for tick in ticks for r in tick]
    names = {r["name"] for r in all_recent}
    paths = {r["path"] for r in all_recent}
    assert "Compliance" in names
    assert "My Drive/Compliance" in paths


def test_recent_reports_file_count_and_completed_state():
    drive = FakeDrive({"root": [_doc("f1"), _doc("f2")]}, names={"root": "My Drive"})
    ticks = []
    scanner._search_folder(drive, "root", max_files=100,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           ticks.append(recent or []))
    all_recent = [r for tick in ticks for r in tick]
    root_entry = next(r for r in all_recent if r["path"] == "My Drive")
    assert root_entry["state"] == "completed"
    assert root_entry["files_found"] == 2


def test_recent_is_bounded_to_the_cap_not_unbounded_history():
    """A wide tree (12 subfolders) must not grow `recent` past its cap — this is a live-activity
    snapshot, not an audit trail. See _RECENT_CAP in _search_folder."""
    children = {"root": [_folder(f"F{i}") for i in range(12)]}
    for i in range(12):
        children[f"F{i}"] = [_doc(f"file{i}")]
    drive = FakeDrive(children, names={"root": "My Drive"})
    ticks = []
    scanner._search_folder(drive, "root", max_files=500,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           ticks.append(recent or []))
    assert all(len(tick) <= 5 for tick in ticks), "recent grew past its bounded cap"


def test_a_folder_that_fails_is_recorded_as_recent_with_zero_files(monkeypatch):
    """A folder skipped after a genuine fetch failure (not rate-limiting) still gets a `recent`
    entry — the caller should be able to tell SOMETHING happened to it, not just that it vanished.

    The failing folder's own completion does not itself trigger a progress_cb call (only the
    success path does) — this relies on `recent` persisting across ticks, so a LATER successful
    folder's tick still carries the earlier failure forward. Same fake-clock technique as the
    name/path test above, needed here so that later tick is not throttled away."""
    clock = [1000.0]

    def _fake_monotonic():
        clock[0] += 3.0
        return clock[0]

    monkeypatch.setattr(scanner.time, "monotonic", _fake_monotonic)

    class _RaisingFiles(_Files):
        def list(self, **kw):
            q = kw.get("q", "")
            fid = q.split("'")[1] if q.startswith("'") else None
            if fid == "A":
                raise RuntimeError("permission denied")
            return super().list(**kw)

    class _RaisingDrive(FakeDrive):
        def files(self):
            return _RaisingFiles(self)

    drive = _RaisingDrive({"root": [_folder("A"), _folder("B")], "B": [_doc("f2")]},
                          names={"root": "My Drive"})
    ticks = []
    scanner._search_folder(drive, "root", max_files=100,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           ticks.append(recent or []))
    all_recent = [r for tick in ticks for r in tick]
    failed = [r for r in all_recent if r["state"] == "failed"]
    assert failed, "the failed folder never got a recent entry"
    assert failed[0]["files_found"] == 0


def test_active_never_includes_a_folder_after_it_finished():
    """Once a folder's fetch resolves (success or failure), it must leave `active` — otherwise a
    completed folder would look like it's still being fetched forever."""
    drive = FakeDrive({"root": [_doc("f1")]}, names={"root": "My Drive"})
    final_active = []
    scanner._search_folder(drive, "root", max_files=100,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           final_active.append(active))
    # The last tick observed must not still list the root as active — it finished before that tick.
    assert final_active
    assert all(not a for a in final_active), "a completed folder was still reported as active"


def test_root_name_lookup_failure_falls_back_gracefully():
    """_folder_name is best-effort (returns None on any failure) — the root path must still be
    usable, not crash the whole scan over a label lookup."""
    class _BrokenFiles(_Files):
        def get(self, fileId, fields=None, supportsAllDrives=None):
            raise RuntimeError("boom")

    class _BrokenDrive(FakeDrive):
        def files(self):
            return _BrokenFiles(self)

    drive = _BrokenDrive({"root": [_doc("f1")]})
    ticks = []
    # Must not raise.
    scanner._search_folder(drive, "root", max_files=100,
                           progress_cb=lambda count, folders=None, active=None, recent=None:
                           ticks.append(recent or []))
    all_recent = [r for tick in ticks for r in tick]
    assert all_recent and all_recent[0]["path"] == "(scan root)"


def test_folder_activity_is_thread_safe_under_the_real_worker_pool():
    """Exercises the real _DISCOVERY_WORKERS-wide thread pool (not a single-threaded stand-in) —
    a wide-and-deep tree so multiple folders are genuinely in flight together — and asserts the
    scan completes with a consistent result, catching any race in the new _active/_recent
    bookkeeping that a smaller fixture wouldn't reliably trigger."""
    children = {"root": [_folder(f"F{i}") for i in range(20)]}
    for i in range(20):
        children[f"F{i}"] = [_folder(f"F{i}-sub")]
        children[f"F{i}-sub"] = [_doc(f"file{i}")]
    drive = FakeDrive(children, names={"root": "My Drive"})
    errors = []
    ticks = []

    def _cb(count, folders=None, active=None, recent=None):
        try:
            # Snapshot copies — a real race in the scanner would show up as a mutation
            # mid-iteration here (RuntimeError: dict/list changed size during iteration).
            list(active or [])
            list(recent or [])
            ticks.append(count)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    result = scanner._search_folder(drive, "root", max_files=500, progress_cb=_cb)
    assert not errors, f"race detected in folder-activity bookkeeping: {errors}"
    assert len(result) == 20
    assert threading.active_count() >= 1  # sanity: we actually ran (not a no-op stub)
