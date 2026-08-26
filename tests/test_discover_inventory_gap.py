"""Two gaps behind "scan still shows 0 documents" on the Discover tab.

Frontend.jsx reads `scope?.inventory?.discovered ?? files.length` for the headline count
(Discover.jsx:242) — `files.length` is `file_records`, which ADR 0020 leaves empty until Assess
opens a file, so a Discover-only run that never populated `scope.inventory` shows 0 no matter how
much it actually found. Two independent ways that happened:

1. `scanner._list`'s `local` and ADC/demo (pinned-folder) branches never set
   `scope_out["inventory"]` at all — only `_search_drive`, `_search_folder`, `_search_folders` and
   `_sp_list` did. A successful local or demo scan still showed "0 documents discovered".

2. `handlers._scan_discover` creates the scan_runs row (status='running', scope=NULL) BEFORE
   calling `scanner._list`. If listing itself raises — an expired Drive token, a transient API
   error, the worker dying mid-list — that half-initialized row is what's left: status stuck at
   'running', scope still NULL, files still 0, discovered_at never stamped. Every symptom in the
   screenshot (0 documents, 0 files, "completion time not recorded", "inventory could not be
   read") is that same row read as a normal empty scan rather than a failed one.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER_MIME = "application/vnd.google-apps.folder"


# ── gap 1: local and ADC/demo branches now report an estate inventory too ──────────────────────

def test_local_scan_populates_scope_inventory(tmp_path, monkeypatch):
    (tmp_path / "a.docx").write_bytes(b"x")
    (tmp_path / "photo.png").write_bytes(b"x")   # not scannable, but part of the estate
    monkeypatch.setenv("ACP_LOCAL_CORPUS", str(tmp_path))

    scope: dict = {}
    inventory_out: list = []
    items = scanner._list("local", scope_out=scope, inventory_out=inventory_out)

    assert len(items) == 1                                   # the .docx only — unchanged behaviour
    assert scope["inventory"]["discovered"] == 2              # BOTH files, the whole estate
    assert scope["inventory"]["assessment_eligible"] == 1


def test_local_scan_with_only_unsupported_files_still_reports_a_nonzero_count(tmp_path, monkeypatch):
    """The exact shape of "0 documents discovered" over a real find: nothing scannable, but the
    estate is not empty."""
    (tmp_path / "clip.mp4").write_bytes(b"x")
    monkeypatch.setenv("ACP_LOCAL_CORPUS", str(tmp_path))

    scope: dict = {}
    items = scanner._list("local", scope_out=scope)
    assert items == []
    assert scope["inventory"]["discovered"] == 1
    assert scope["inventory"]["assessment_eligible"] == 0


class _FakeFiles:
    def __init__(self, batch):
        self._batch = batch

    def list(self, **kw):
        return self

    def get(self, fileId=None, **kw):
        return self

    def execute(self, **kw):
        return {"files": self._batch, "name": "Demo"}


class _FakeSvc:
    def __init__(self, batch):
        self._files = _FakeFiles(batch)

    def files(self):
        return self._files


def test_demo_folder_scan_populates_scope_inventory():
    """`folder=""` is the ADC/demo pinned-folder branch (the trailing `else` in `_list`) — the
    other source that never set scope_out["inventory"]."""
    batch = [
        {"id": "d1", "name": "a.docx", "mimeType": DOCX},
        {"id": "d2", "name": "photo.png", "mimeType": "image/png"},
    ]
    svc = _FakeSvc(batch)
    scope: dict = {}
    items = scanner._list("drive", svc, folder="", scope_out=scope)

    assert len(items) == 1
    assert scope["kind"] == "folder"
    assert scope["inventory"]["discovered"] == 2
    assert scope["inventory"]["assessment_eligible"] == 1


# ── gap 2: a listing failure marks the run failed instead of leaving it stuck ──────────────────

def test_a_listing_failure_marks_the_scan_failed_and_still_propagates(isolated_store, monkeypatch):
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    def _boom(*a, **k):
        raise RuntimeError("Drive token expired")
    monkeypatch.setattr(scanner, "_list", _boom)

    with pytest.raises(RuntimeError, match="Drive token expired"):
        handlers._scan_discover({"scan_id": "s-boom", "source": "local", "user": None},
                                {"scan_id": "s-boom"})

    run = isolated_store.get_scan("s-boom")["run"]
    assert run["status"] == "failed"                          # not stuck at 'running'
    decisions = isolated_store.list_decisions("s-boom")
    assert any(d["action"] == "scan.discover_failed" for d in decisions)


def test_a_retry_after_a_listing_failure_resets_status_to_running(isolated_store, monkeypatch):
    """worker.py retries the same job on a transient error; the next _scan_discover attempt calls
    init_scan_run again (no inventory was persisted, so the checkpoint-resume path is not taken)
    and that legitimately overwrites 'failed' back to 'running' — this is a between-attempts
    marker, not a terminal one."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    calls = {"n": 0}

    def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return []
    monkeypatch.setattr(scanner, "_list", _flaky)

    with pytest.raises(RuntimeError):
        handlers._scan_discover({"scan_id": "s-retry", "source": "local", "user": None},
                                {"scan_id": "s-retry"})
    assert isolated_store.get_scan("s-retry")["run"]["status"] == "failed"

    handlers._scan_discover({"scan_id": "s-retry", "source": "local", "user": None},
                            {"scan_id": "s-retry"})
    assert isolated_store.get_scan("s-retry")["run"]["status"] == "discovered"
