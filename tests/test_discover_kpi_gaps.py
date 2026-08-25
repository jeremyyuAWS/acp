"""Discover KPI gaps: metadata completeness (§6.3) and inventory save KPI (§6.6).

Verifies:
  1. scanner.run_scan emits metadata_complete / metadata_incomplete in the progress payload.
  2. The deferred _scan_discover path emits save_new / save_updated / ... via core.update_job()
     when the job dict carries an 'id' (the live-worker case).
  3. The deferred path still succeeds when the job dict has no 'id' (existing callers).
"""
import sys
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


def test_deferred_path_second_run_shows_updated_count(isolated_store, monkeypatch):
    """Re-running discover on the same scan emits save_updated > 0 for existing rows."""
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

    job_id_2 = "j-run2"
    core.JOBS[job_id_2] = {"phase": "queued"}
    handlers._scan_discover(
        {"scan_id": "sd-rerun", "source": "local", "user": None},
        {"scan_id": "sd-rerun", "id": job_id_2},
    )

    state2 = core.JOBS.get(job_id_2, {})
    assert state2.get("save_new") == 0, f"expected 0 new on re-run, got {state2}"
    assert state2.get("save_updated") == 1, f"expected 1 updated on re-run, got {state2}"
