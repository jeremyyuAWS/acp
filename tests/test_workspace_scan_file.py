"""api/handlers.py::_workspace_scan_file (ADR 0044) — assessing a stored workspace upload
through the SAME per-file engine every connector-sourced scan already uses.

Same wiring pattern as test_scan_pause_resume.py's handler-level tests: monkeypatch
core.store, core.active_rubric, lf.flush, and (here) workspace_blob.download_document_bytes —
no real Azure, no real .NET/PDF engine call (that's _analyse_and_persist_one's own concern,
already tested elsewhere; this file tests the NEW code around it: blob download, temp-file
handoff, and the done-counter/finalize trigger).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"


def _wire(monkeypatch, st, count_files_done_fn):
    import core
    import handlers
    import lf
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(lf, "flush", lambda: None)
    monkeypatch.setattr(core, "active_rubric", lambda: type("R", (), {"hash": "test-hash"})())
    monkeypatch.setattr(st, "count_files_done", count_files_done_fn)


def _payload(**over):
    p = {"scan_id": "s1", "workspace_id": "ws1", "document_id": "doc1", "version_id": "v1",
         "file": "report.pdf", "checksum": "h1", "user": OWNER}
    p.update(over)
    return p


def test_downloads_the_blob_and_hands_a_local_path_to_the_engine(isolated_store, monkeypatch):
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (1, 1))
    monkeypatch.setattr(workspace_blob, "download_document_bytes",
                        lambda *a, **kw: b"%PDF-1.7 fake bytes")
    captured = {}

    def fake_analyse(scan_id, item, source, pii, svc, toks, now, _lf, **kw):
        captured.update(item=item, source=source, svc=svc, toks=toks)
        # Prove the path is real and contains the downloaded bytes.
        assert Path(item["path"]).read_bytes() == b"%PDF-1.7 fake bytes"
    monkeypatch.setattr(handlers, "_analyse_and_persist_one", fake_analyse)

    handlers._workspace_scan_file(_payload(), {})

    assert captured["source"] == "workspace"
    assert captured["svc"] is None
    assert captured["item"]["file"] == "report.pdf"
    assert captured["item"]["checksum"] == "h1"


def test_calls_the_engine_with_incremental_false(isolated_store, monkeypatch):
    """Cross-scan reuse is keyed on drive_file_id, which a workspace file never has — must not
    be attempted, rather than silently never matching."""
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (1, 1))
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: b"bytes")
    captured = {}
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda scan_id, item, source, pii, svc, toks, now, _lf, **kw:
                            captured.update(kw))

    handlers._workspace_scan_file(_payload(), {})

    assert captured["incremental"] is False
    assert captured["user"] == OWNER
    assert captured["rubric_hash"] == "test-hash"


def test_does_not_call_the_engine_when_the_blob_is_not_retrievable(isolated_store, monkeypatch):
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (1, 1))
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: None)
    analysed = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda *a, **kw: analysed.append(True))

    handlers._workspace_scan_file(_payload(), {})

    assert analysed == [], "the engine must not be called with no bytes to analyse"


def test_blob_unreadable_still_saves_an_error_file_record(isolated_store, monkeypatch):
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (1, 1))
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(handlers, "_analyse_and_persist_one", lambda *a, **kw: None)

    handlers._workspace_scan_file(_payload(), {})

    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT status FROM file_records WHERE scan_id=%s AND file=%s", ("s1", "report.pdf"))
        row = isolated_store._db.fetchone(cur)
    assert row is not None and row["status"] == "error"


def test_enqueues_scan_finalize_once_the_file_count_is_reached(isolated_store, monkeypatch):
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (1, 1))
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: b"bytes")
    monkeypatch.setattr(handlers, "_analyse_and_persist_one", lambda *a, **kw: None)
    enqueued = []
    monkeypatch.setattr(isolated_store, "enqueue_job",
                        lambda jtype, payload, **kw: enqueued.append((jtype, payload)))

    handlers._workspace_scan_file(_payload(), {})

    assert len(enqueued) == 1
    jtype, payload = enqueued[0]
    assert jtype == "scan_finalize"
    assert payload["scan_id"] == "s1"
    assert payload["source"] == "workspace"


def test_does_not_finalize_before_the_count_is_reached(isolated_store, monkeypatch):
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (0, 3))   # not done yet
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: b"bytes")
    monkeypatch.setattr(handlers, "_analyse_and_persist_one", lambda *a, **kw: None)
    enqueued = []
    monkeypatch.setattr(isolated_store, "enqueue_job",
                        lambda jtype, payload, **kw: enqueued.append((jtype, payload)))

    handlers._workspace_scan_file(_payload(), {})

    assert enqueued == []


def test_skips_analysis_while_the_scan_is_paused(isolated_store, monkeypatch):
    import handlers
    import workspace_blob
    _wire(monkeypatch, isolated_store, lambda sid: (0, 1))
    monkeypatch.setattr(handlers, "scan_paused", lambda scan_id: True)
    called = []
    monkeypatch.setattr(workspace_blob, "download_document_bytes",
                        lambda *a, **kw: called.append(True))
    monkeypatch.setattr(handlers, "_analyse_and_persist_one", lambda *a, **kw: called.append(True))

    handlers._workspace_scan_file(_payload(), {})

    assert called == []
