"""ADR 0003 Phase 3 execute path — safety invariants.

Fake Drive service (records calls, no network) + fresh SQLite store. The
invariants under test are the ones that make executing dispositions safe:
delete is ALWAYS trash (files().delete must never be called), approval-gated
policies never touch a file at execute time, and a (doc, policy) pair with a
live outcome is never re-queued.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import disposition  # noqa: E402


class _Call:
    """Chainable fake for googleapiclient's fluent API: svc.files().update(...).execute()."""
    def __init__(self, log, name, **kw):
        self.log, self.name, self.kw = log, name, kw

    def execute(self):
        self.log.append((self.name, self.kw))
        if self.name == "get":
            return {"name": "old-name.docx", "parents": ["root-folder"]}
        if self.name == "list":
            return {"files": [{"id": "existing-folder"}]}
        return {"id": "resp-id"}


class FakeDrive:
    def __init__(self):
        self.calls = []

    def files(self):
        outer = self
        class _F:
            def update(self, **kw): return _Call(outer.calls, "update", **kw)
            def get(self, **kw): return _Call(outer.calls, "get", **kw)
            def list(self, **kw): return _Call(outer.calls, "list", **kw)
            def create(self, **kw): return _Call(outer.calls, "create", **kw)
            def delete(self, **kw): raise AssertionError("files().delete() must NEVER be called")
        return _F()


def _doc(doc_id="drive:f123", source="drive"):
    return {"doc_id": doc_id, "source": source, "path": "x.docx", "department": "Legal",
            "created_at": "2020-01-01T00:00:00+00:00"}


def test_delete_is_always_trash():
    svc = FakeDrive()
    result, detail = disposition.execute_action(_doc(), "delete", {}, svc)
    assert result == "applied" and "trash" in detail
    assert svc.calls == [("update", {"fileId": "f123", "body": {"trashed": True}})]


def test_archive_moves_to_folder():
    svc = FakeDrive()
    result, detail = disposition.execute_action(_doc(), "archive", {}, svc)
    assert result == "applied"
    kinds = [k for k, _ in svc.calls]
    assert "update" in kinds and ("list" in kinds or "create" in kinds)


def test_rename_uses_template():
    svc = FakeDrive()
    result, detail = disposition.execute_action(
        _doc(), "rename", {"template": "{name} [RETIRED]"}, svc)
    assert result == "applied" and "old-name.docx [RETIRED]" in detail


def test_leave_needs_no_drive():
    result, detail = disposition.execute_action(_doc(), "leave", {}, None)
    assert result == "applied"


def test_non_drive_source_fails_cleanly():
    result, detail = disposition.execute_action(
        _doc(doc_id="local:abc", source="local"), "delete", {}, FakeDrive())
    assert result == "failed" and "unsupported source" in detail


def test_missing_drive_connection_fails_cleanly():
    result, detail = disposition.execute_action(_doc(), "archive", {}, None)
    assert result == "failed" and "Drive" in detail


def test_action_exception_becomes_failed():
    class Boom(FakeDrive):
        def files(self):
            raise RuntimeError("api down")
    result, detail = disposition.execute_action(_doc(), "delete", {}, Boom())
    assert result == "failed" and "RuntimeError" in detail


# ── Store-level: audit lifecycle + idempotency ────────────────────────────────

@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "disp-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def test_pending_blocks_requeue_but_rejected_does_not(store):
    store.create_disposition_audit("a1", doc_id="drive:f1", policy_id="p1",
                                   action="archive", result="pending_approval", detail="q")
    assert store.doc_has_disposition("drive:f1", "p1") is True
    store.set_disposition_audit_result("a1", "rejected", "declined")
    assert store.doc_has_disposition("drive:f1", "p1") is False   # can be re-proposed
    store.create_disposition_audit("a2", doc_id="drive:f1", policy_id="p1",
                                   action="archive", result="applied", detail="done")
    assert store.doc_has_disposition("drive:f1", "p1") is True    # applied blocks forever


def test_audit_list_filters(store):
    store.create_disposition_audit("b1", doc_id="d1", policy_id="p1",
                                   action="delete", result="pending_approval", detail="")
    store.create_disposition_audit("b2", doc_id="d2", policy_id="p1",
                                   action="delete", result="applied", detail="")
    pending = store.list_disposition_audit(result="pending_approval")
    assert [r["id"] for r in pending] == ["b1"]
    assert len(store.list_disposition_audit(policy_id="p1")) == 2
