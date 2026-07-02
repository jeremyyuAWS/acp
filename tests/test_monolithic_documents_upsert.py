"""Monolithic scans must populate the documents table (ADR 0003 Phase 1).

The fan-out path upserts per file in handlers._analyse_and_persist_one; the
monolithic path (store.save_scan) used to skip the document layer entirely,
leaving disposition/triage blind after a plain POST /scans run.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store():
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "mono-test.db"
    store_mod._SQLITE_PATH = tmp
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def _report(files):
    return {
        "_scan_id": "mono1",
        "rubric": {"name": "r", "version": "1", "hash": "h"},
        "summary": {"files": len(files), "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 50},
        "started_at": "2026-07-02T00:00:00+00:00",
        "completed_at": "2026-07-02T00:01:00+00:00",
        "source": "local",
        "owner": "mono@test",
        "files": files,
    }


def test_save_scan_upserts_documents(store):
    files = [
        {"file": "a.pdf", "engine": "python/pdf", "status": "done", "score": 70, "compliant": 0,
         "skipped_rules": 0, "issues": [], "checksum": "c1",
         "pii": {"severity": "critical", "total": 3, "findings": []}},
        {"file": "b.html", "engine": "python/html", "status": "done", "score": 95, "compliant": 1,
         "skipped_rules": 0, "issues": [], "checksum": "c2", "pii": None},
    ]
    store.save_scan(_report(files))
    docs = {d["path"]: d for d in store.list_all_documents()}
    assert set(docs) == {"a.pdf", "b.html"}
    assert docs["a.pdf"]["source"] == "local"
    assert docs["a.pdf"]["owner"] == "mono@test"
    # PII-heavy low-score file must triage hotter than the clean one
    assert docs["a.pdf"]["triage_score"] > docs["b.html"]["triage_score"]


def test_save_scan_document_layer_never_breaks_save(store, monkeypatch):
    import documents
    monkeypatch.setattr(documents, "resolve_doc_id", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    files = [{"file": "x.pdf", "engine": "python/pdf", "status": "done", "score": 50,
              "compliant": 0, "skipped_rules": 0, "issues": [], "checksum": None, "pii": None}]
    sid = store.save_scan(_report(files))          # must not raise
    assert store.get_scan(sid) is not None         # scan itself saved fine
    assert store.list_all_documents() == []        # document layer lost, scan intact
