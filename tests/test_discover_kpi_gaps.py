"""Discover KPI gaps: metadata completeness (§6.3) and inventory save KPI (§6.6).

Verifies:
  1. scanner.run_scan emits metadata_complete / metadata_incomplete in the progress payload.
  2. The deferred _scan_discover path emits save_new / save_updated / ... via core.update_job()
     when the job dict carries an 'id' (the live-worker case).
  3. The deferred path still succeeds when the job dict has no 'id' (existing callers).
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


# ── metadata completeness in the progress payload (§6.3) ─────────────────────

def test_run_scan_emits_metadata_complete_and_incomplete(isolated_store, monkeypatch, tmp_path):
    """scanner.run_scan must emit metadata_complete / metadata_incomplete in progress events.

    The metadata counts are computed right after _list() — before any download or analysis —
    so mocking _download to raise PermissionError skips the expensive work while still
    capturing the 'discovering' phase event that carries the KPI fields.
    """
    import core
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    items = [
        {"name": "a.docx", "id": "d1", "mime": _DOCX,
         "owner": "alice@x.com", "source_modified": "2026-01-01"},   # complete
        {"name": "b.pdf", "id": "d2", "mime": "application/pdf",
         "owner": None, "source_modified": None},                      # incomplete
        {"name": "c.html", "id": "d3", "mime": "text/html",
         "owner": "bob@x.com", "source_modified": None},               # incomplete
    ]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
    # PermissionError → inaccessible, not a test failure. Skips downloading/analysis entirely.
    monkeypatch.setattr(scanner, "_download", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))

    captured = []
    isolated_store.init_scan_run("s-meta", "local", 3, "2026-01-01T00:00:00+00:00",
                                 "acp", "h1", owner=None)

    try:
        scanner.run_scan(source="local", progress=lambda p: captured.append(p),
                         scan_id="s-meta")
    except Exception:
        pass  # scan may raise after all files are inaccessible; we only need the discovering event

    meta_events = [p for p in captured if "metadata_complete" in p]
    assert meta_events, f"No progress event with metadata_complete; phases seen: {[p.get('phase') for p in captured]}"

    ev = meta_events[0]
    # 1 complete (a.docx), 2 incomplete (b.pdf + c.html)
    assert ev["metadata_complete"] == 1, f"expected 1 complete: {ev}"
    assert ev["metadata_incomplete"] == 2, f"expected 2 incomplete: {ev}"
    assert ev["metadata_complete"] + ev["metadata_incomplete"] == 3, "must sum to files_found"


def test_metadata_kpi_fields_present_in_reading_phase(isolated_store, monkeypatch):
    """metadata_complete / metadata_incomplete must also appear in 'reading' phase events."""
    import core
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    items = [
        {"name": "a.docx", "id": "d1", "mime": _DOCX,
         "owner": "alice@x.com", "source_modified": "2026-01-01"},
        {"name": "b.docx", "id": "d2", "mime": _DOCX,
         "owner": None, "source_modified": None},
    ]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
    # Raise PermissionError immediately so we capture the reading-phase header event before skip.
    # The 'reading' event fires at the start of EACH file's loop iteration, before _download.
    monkeypatch.setattr(scanner, "_download", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))

    captured = []
    isolated_store.init_scan_run("s-reading", "local", 2, "2026-01-01T00:00:00+00:00",
                                 "acp", "h1", owner=None)

    try:
        scanner.run_scan(source="local", progress=lambda p: captured.append(p),
                         scan_id="s-reading")
    except Exception:
        pass

    reading_events = [p for p in captured if p.get("phase") == "reading" and "metadata_complete" in p]
    assert reading_events, f"No 'reading' phase event with metadata_complete; got phases: {[p.get('phase') for p in captured]}"
    ev = reading_events[0]
    assert "metadata_complete" in ev and "metadata_incomplete" in ev


# ── deferred path inventory save KPI via core.update_job (§6.6) ──────────────

def test_deferred_path_emits_save_kpis_when_job_has_id(isolated_store, monkeypatch):
    """_scan_discover must call core.update_job with save_new / save_updated / save_unchanged /
    save_failed when the job dict carries an 'id' (as the live worker sets it)."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    items = [
        {"name": "a.docx", "id": "d1", "mime": _DOCX},
        {"name": "b.pdf", "id": "d2", "mime": "application/pdf"},
    ]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    job_id = "j-deferred-kpi"
    core.JOBS[job_id] = {"phase": "queued"}

    handlers._scan_discover(
        {"scan_id": "sd-kpi", "source": "local", "user": None},
        {"scan_id": "sd-kpi", "id": job_id},
    )

    state = core.JOBS.get(job_id, {})
    assert "save_new" in state, f"save_new missing from job state: {state}"
    assert "save_updated" in state, f"save_updated missing from job state: {state}"
    assert "save_unchanged" in state, f"save_unchanged missing from job state: {state}"
    assert "save_failed" in state, f"save_failed missing from job state: {state}"
    # First run: both items are new rows.
    assert state["save_new"] == 2, f"expected 2 new, got {state}"
    assert state["save_updated"] == 0, f"expected 0 updated, got {state}"


def test_deferred_path_without_job_id_still_succeeds(isolated_store, monkeypatch):
    """_scan_discover must not crash when job dict has no 'id' (existing test pattern)."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    items = [{"name": "x.docx", "id": "x1",
              "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    # No 'id' in job dict — must not raise.
    handlers._scan_discover(
        {"scan_id": "sd-noid", "source": "local", "user": None},
        {"scan_id": "sd-noid"},
    )
    inv = isolated_store.list_inventory("sd-noid")
    assert len(inv) == 1  # inventory was still persisted correctly


def test_deferred_path_second_run_uses_checkpoint_resume(isolated_store, monkeypatch, capsys):
    """A retry of _scan_discover on the same scan_id skips listing + inventory save
    (checkpoint resume) and jumps straight to lifecycle evaluation."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    items = [{"name": "a.docx", "id": "d1", "mime": _DOCX}]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    job_id_1 = "j-run1"
    core.JOBS[job_id_1] = {"phase": "queued"}
    handlers._scan_discover(
        {"scan_id": "sd-rerun", "source": "local", "user": None},
        {"scan_id": "sd-rerun", "id": job_id_1},
    )
    assert core.JOBS[job_id_1].get("save_new") == 1

    list_calls = []
    real_list = scanner._list
    def _tracking_list(*a, **k):
        list_calls.append(1)
        return real_list(*a, **k)
    monkeypatch.setattr(scanner, "_list", _tracking_list)

    job_id_2 = "j-run2"
    core.JOBS[job_id_2] = {"phase": "queued"}
    handlers._scan_discover(
        {"scan_id": "sd-rerun", "source": "local", "user": None},
        {"scan_id": "sd-rerun", "id": job_id_2},
    )

    assert len(list_calls) == 0, "checkpoint should skip _list on retry"
    state2 = core.JOBS.get(job_id_2, {})
    assert state2.get("phase") == "done", f"retry should still complete: {state2}"
    assert "save_new" not in state2, "checkpoint skips add_inventory, so no save KPIs"
    out = capsys.readouterr().out
    assert "retry detected" in out, "checkpoint should log retry detection"


# ── deferred path done-phase emission (§6.7) ──────────────────────────────────

def test_deferred_path_emits_done_phase_with_lifecycle_fields(isolated_store, monkeypatch):
    """_scan_discover must emit phase='done' with lifecycle_* fields so the DiscoverRunProgress
    completion summary (which reads lifecycle_archive / lifecycle_delete / lifecycle_tagged)
    is shown for the deferred path before the UI detects status='discovered' and navigates away.
    """
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    items = [
        {"name": "a.docx", "id": "d1", "mime": _DOCX},
        {"name": "b.pdf", "id": "d2", "mime": "application/pdf"},
    ]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    job_id = "j-done-phase"
    core.JOBS[job_id] = {"phase": "queued"}

    handlers._scan_discover(
        {"scan_id": "sd-done", "source": "local", "user": None},
        {"scan_id": "sd-done", "id": job_id},
    )

    state = core.JOBS.get(job_id, {})
    assert state.get("phase") == "done", \
        f"expected phase='done' after _scan_discover, got phase={state.get('phase')!r}; state={state}"
    # Completion summary fields must be present (can be 0 when no lifecycle rules are configured).
    for field in ("lifecycle_matches", "lifecycle_archive", "lifecycle_delete", "lifecycle_tagged"):
        assert field in state, f"{field} missing from done-phase job state: {state}"


def test_deferred_path_emits_saving_phase_before_add_inventory(isolated_store, monkeypatch):
    """_scan_discover must set phase='saving' BEFORE the inventory is persisted, so
    DiscoverRunProgress.jsx's "Saving inventory" step shows as active for that window instead
    of silently vanishing into 'discovering' — found live 2026-08-26 alongside the missing
    folder count: the save always ran here, before lifecycle rules, but never got a live phase
    of its own."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    items = [{"name": "a.docx", "id": "d1", "mime": _DOCX}]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    job_id = "j-saving-phase"
    core.JOBS[job_id] = {"phase": "queued"}

    seen_phase_at_save = []
    real_add_inventory = isolated_store.add_inventory

    def _spy_add_inventory(scan_id, inv):
        # Snapshot right when the save happens — before _scan_discover moves on to lifecycle,
        # which would otherwise overwrite 'phase' and hide the bug this test exists to catch.
        seen_phase_at_save.append(core.JOBS.get(job_id, {}).get("phase"))
        return real_add_inventory(scan_id, inv)

    monkeypatch.setattr(isolated_store, "add_inventory", _spy_add_inventory)

    handlers._scan_discover(
        {"scan_id": "sd-saving-phase", "source": "local", "user": None},
        {"scan_id": "sd-saving-phase", "id": job_id},
    )

    assert seen_phase_at_save == ["saving"], \
        f"expected phase='saving' at the moment add_inventory ran, got {seen_phase_at_save}"
    # And the phase must move on afterwards — lifecycle rules evaluate against what was just
    # persisted, so 'saving' must not be the terminal phase.
    final_state = core.JOBS.get(job_id, {})
    assert final_state.get("phase") == "done", \
        f"expected the scan to still reach phase='done', got {final_state}"


# ── lifecycle per-file resilience (§6.8) ──────────────────────────────────────

def test_lifecycle_eval_survives_one_bad_file(isolated_store, monkeypatch):
    """One malformed inventory row must not crash the entire lifecycle rule pass.

    The fix wraps per-file match/resolve in try/except so the remaining 49,999
    files are still evaluated and their tags/statuses are flushed.
    """
    import core
    import disposition
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)

    scan_id = "sd-resilient"
    isolated_store.init_scan_run(scan_id, "local", 3, "2026-01-01T00:00:00+00:00",
                                 "acp", "h1", owner=None)
    # Three inventory rows — the second one will poison disposition.matches.
    isolated_store.add_inventory(scan_id, [
        {"file": name, "path": f"/{name}", "doc_class": "docx",
         "size_kb": 10, "owner": "a@b.com", "created_at": "2020-01-01"}
        for name in ("good1.docx", "bad.docx", "good2.docx")
    ])

    # A policy that matches everything.
    import json as _json
    isolated_store.create_disposition_policy(
        "pol-tag-all",
        name="tag-all", action="tag", enabled=True, requires_approval=False,
        match=_json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
        action_config=_json.dumps({"tags": ["auto"]}),
        owner_email="a@b.com",
    )

    real_matches = disposition.matches

    def _boom(doc, match):
        if "bad.docx" in (doc.get("doc_id") or ""):
            raise ValueError("simulated bad row")
        return real_matches(doc, match)

    monkeypatch.setattr(disposition, "matches", _boom)

    result = handlers._evaluate_discover_lifecycle_rules(scan_id, "local", "a@b.com")

    assert result["lifecycle_errors"] == 1, f"expected 1 error, got {result}"
    assert result["files_evaluated"] == 3, f"all 3 files should be evaluated, got {result}"
    # The two good files should still have been tagged.
    assert result["lifecycle_tagged"] == 2, \
        f"expected 2 tagged (good files), got {result['lifecycle_tagged']}; {result}"


# ── BFS folder resilience (§6.8) ────────────────────────────────────────────

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
FOLDER = "application/vnd.google-apps.folder"


class _Req:
    """Minimal stub for a Drive API request object."""

    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _BoomReq:
    """A request that always raises — simulates an inaccessible folder."""

    def execute(self, num_retries=0):
        raise PermissionError("simulated 403 from Drive API")


class _BFSFiles:
    """Stub for svc.files() that returns _BoomReq for one specific folder."""

    def __init__(self, children, boom_folder_id):
        self._children = children
        self._boom = boom_folder_id

    def list(self, **kw):
        q = kw.get("q", "")
        if q.startswith("'"):
            fid = q.split("'")[1]
            if fid == self._boom:
                return _BoomReq()
            return _Req({"files": self._children.get(fid, [])})
        return _Req({"files": []})


class _BFSDrive:
    """Fake Drive service for BFS tests with one poisoned folder."""

    def __init__(self, children, boom_folder_id):
        self._files = _BFSFiles(children, boom_folder_id)

    def files(self):
        return self._files


def test_search_folder_survives_one_inaccessible_subfolder(monkeypatch):
    """One folder that raises on listing must not abort the entire BFS.

    The fix wraps fut.result() in try/except so the remaining subtrees are
    still walked and their files returned.
    """
    import scanner

    core_mod = types.ModuleType("core")
    core_mod.store = types.SimpleNamespace(get_drive_mirror_folder=lambda: "Remediated")
    monkeypatch.setitem(sys.modules, "core", core_mod)

    children = {
        "root": [
            {"id": "ok_folder", "name": "OK", "mimeType": FOLDER},
            {"id": "bad_folder", "name": "Bad", "mimeType": FOLDER},
        ],
        "ok_folder": [
            {"id": "f1", "name": "deck.pptx", "mimeType": PPTX, "md5Checksum": "aaa"},
        ],
        # bad_folder → _BoomReq raises PermissionError
    }
    svc = _BFSDrive(children, boom_folder_id="bad_folder")
    scope_out = {}

    result = scanner._search_folder(svc, "root", max_files=50,
                                     exclude_remediated=True, scope_out=scope_out)

    assert len(result) == 1, f"expected 1 file from the accessible folder, got {len(result)}"
    assert result[0]["name"] == "deck.pptx"
    assert scope_out.get("skipped_errors") == 1, \
        f"expected 1 skipped_errors in scope_out, got {scope_out}"
