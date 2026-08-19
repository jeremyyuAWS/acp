"""The default (non-fanout) scan path evaluates archival/deletion rules too.

Historically only the fanout path (_scan_discover) persisted per-file inventory and ran the lifecycle
rules; a normal in-process Discover skipped both, so archive/delete rules were silently not evaluated
and the per-file inventory the Assess eligibility count reads was never populated. All paths now route
through handlers.persist_discovery_inventory — these tests pin that shared helper's behaviour.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _inv():
    return [
        {"file": "/Archive/old.docx", "path": "/Archive/old.docx", "parent_folder": "/Archive",
         "mime": _DOCX, "doc_class": "docx", "owner": "cfo@x.com"},
        {"file": "/Current/new.docx", "path": "/Current/new.docx", "parent_folder": "/Current",
         "mime": _DOCX, "doc_class": "docx", "owner": "cfo@x.com"},
    ]


def _archive_rule(st):
    st.create_disposition_policy(
        "p-arch", name="Archive the /Archive folder",
        match=json.dumps([{"field": "parent_folder", "op": "prefix", "value": "/Archive"}]),
        action="archive", action_config="{}", requires_approval=False, enabled=True)


def _status(st, scan_id, file):
    return (st.get_lifecycle_status(scan_id, file) or {}).get("lifecycle_status", "Active")


def test_persists_inventory_and_marks_matching_candidates(isolated_store, monkeypatch):
    import core, handlers
    monkeypatch.setattr(core, "store", isolated_store)
    st = isolated_store
    _archive_rule(st)
    handlers.persist_discovery_inventory("s1", _inv(), "local", "admin@x.com")
    # per-file inventory is now persisted — the grain the Assess eligibility count reads
    assert st.count_inventory("s1") == 2
    assert _status(st, "s1", "/Archive/old.docx") == "Archive Candidate"   # matched the folder rule
    assert _status(st, "s1", "/Current/new.docx") == "Active"              # unmatched — untouched


def test_no_enabled_rules_leaves_everything_active(isolated_store, monkeypatch):
    import core, handlers
    monkeypatch.setattr(core, "store", isolated_store)
    st = isolated_store
    handlers.persist_discovery_inventory("s1", _inv(), "local", "admin@x.com")
    assert st.count_inventory("s1") == 2                                   # inventory still persisted
    assert _status(st, "s1", "/Archive/old.docx") == "Active"
    assert _status(st, "s1", "/Current/new.docx") == "Active"


def test_re_running_is_idempotent(isolated_store, monkeypatch):
    import core, handlers
    monkeypatch.setattr(core, "store", isolated_store)
    st = isolated_store
    _archive_rule(st)
    handlers.persist_discovery_inventory("s1", _inv(), "local", "admin@x.com")
    handlers.persist_discovery_inventory("s1", _inv(), "local", "admin@x.com")   # re-run
    assert st.count_inventory("s1") == 2                                   # de-duped on (scan_id, file)
    assert _status(st, "s1", "/Archive/old.docx") == "Archive Candidate"   # candidate preserved, not reset


def test_scan_job_wires_run_scan_inventory_into_the_lifecycle_pass(isolated_store, monkeypatch):
    """End-to-end on the monolithic 'scan' job (the path a non-fanout durable scan takes): run_scan
    fills inventory_out, and the handler now persists it and evaluates the enabled archive rule —
    proving the wiring, not just the helper. Modeled on test_jobs.test_scan_handler_*."""
    import core, scanner, handlers  # noqa: F401 — registers the 'scan' handler
    import worker
    store = isolated_store
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(store, "get_ai_enabled", lambda: True)
    _archive_rule(store)

    def fake_run_scan(source, *, drive_token=None, sp_token=None, folder=None, ai_enabled=True,
                      scan_id=None, user=None, detect_pii=True, exclude_remediated=False, inventory_out=None):
        if inventory_out is not None:
            inventory_out.extend(_inv())          # what a real discovery would collect
        return {"_scan_id": scan_id, "summary": {"files": 1, "certifiable": 1, "uncertain": 0,
                "error": 0, "avg_score": 100}, "rubric": {"name": "r", "version": "1", "hash": "h"},
                "started_at": "t0", "completed_at": "t1", "source": source, "files": []}
    monkeypatch.setattr(handlers, "run_scan", fake_run_scan)

    sid = "scan-lc-1"
    core.register_scan_tokens(sid, drive="tok")
    jid = store.enqueue_job("scan", {"source": "drive", "scan_id": sid, "ai": True, "user": "admin@x.com"}, scan_id=sid)
    assert worker.JobWorker(store, worker_id="w-lc").run_once() is True
    assert store.get_job(jid)["status"] == "done"
    assert store.count_inventory(sid) == 2                                 # inventory persisted on the default path
    assert _status(store, sid, "/Archive/old.docx") == "Archive Candidate" # rule evaluated during the scan
    assert _status(store, sid, "/Current/new.docx") == "Active"
