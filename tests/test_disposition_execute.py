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


def test_tag_executes_without_drive_and_needs_no_svc():
    # Tag is metadata-only: applies for any source, with svc=None, never touching Drive.
    result, detail = disposition.execute_action(
        _doc(doc_id="sp:abc", source="sharepoint"), "tag", {"tags": ["legacy", "review"]}, None)
    assert result == "applied" and detail == "tagged: legacy, review"


def test_tag_dedupes_and_trims_in_detail():
    result, detail = disposition.execute_action(
        _doc(), "tag", {"tags": [" legacy ", "legacy", "", "review"]}, None)
    assert result == "applied" and detail == "tagged: legacy, review"


def test_tag_with_no_tags_fails_cleanly():
    result, detail = disposition.execute_action(_doc(), "tag", {"tags": []}, None)
    assert result == "failed" and "no tags" in detail


def test_validate_action_config_requires_tags_for_tag():
    disposition.validate_action_config("tag", {"tags": ["x"]})       # ok, no raise
    disposition.validate_action_config("archive", {})               # non-tag unaffected
    for bad in ({}, {"tags": []}, {"tags": ["", "  "]}, None):
        with pytest.raises(ValueError):
            disposition.validate_action_config("tag", bad)


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


# ── Route-level: Tag policy end-to-end (execute writes file_tags via store) ────

class _Req:
    """Minimal stand-in for a FastAPI Request — headers.get + a bare .state, which
    is all the disposition routes touch (no Drive token → svc is None, fine for tag)."""
    def __init__(self, token=None):
        self.headers = {"x-drive-token": token} if token else {}
        self.state = type("S", (), {})()


@pytest.fixture()
def routed(monkeypatch):
    """Fresh store wired into core + owner gate disabled — routes act as owner."""
    import core
    import store as store_mod
    import routes.disposition as rd
    tmp = Path(tempfile.mkdtemp()) / "disp-route.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(core, "OWNER_EMAIL", "")
    return rd, core, st


def _seed_doc(st, doc_id="drive:t1", path="Reports/old.docx", source="drive"):
    st.upsert_document(doc_id, source=source, path=path, content_hash=None, owner=None,
                       created_at="2019-01-01T00:00:00+00:00",
                       last_seen="2019-01-01T00:00:00+00:00", triage_score=0, triage_rationale="",
                       owner_email="demo")


def _make_tag_policy(rd, name, *, requires_approval, tags=("legacy", "review")):
    body = rd.PolicyCreate(name=name, match=[{"field": "source", "op": "eq", "value": "drive"}],
                           action="tag", action_config={"tags": list(tags)},
                           requires_approval=requires_approval, enabled=True)
    return rd.create_policy(body, _Req())["policy_id"]


def test_tag_policy_execute_writes_file_tags_idempotently(routed):
    rd, core, st = routed
    _seed_doc(st)
    pid = _make_tag_policy(rd, "tag legacy drive", requires_approval=False)

    summary = rd.execute_policy(pid, _Req())
    assert summary["matched"] == 1 and summary["applied"] == 1

    tags = st.list_file_tags("drive:t1", "Reports/old.docx")
    assert sorted(t["tag"] for t in tags) == ["legacy", "review"]
    assert all(t["kind"] == "system" and t["rule_id"] == pid for t in tags)

    # Idempotent: the (doc, policy) pair now has a live outcome, so a re-run skips it
    # and the tag set is unchanged (file_tags PK also makes the write itself idempotent).
    summary2 = rd.execute_policy(pid, _Req())
    assert summary2["applied"] == 0 and summary2["skipped"] == 1
    assert len(st.list_file_tags("drive:t1", "Reports/old.docx")) == 2


def test_execute_policy_audit_id_is_deterministic_per_doc_and_policy(routed):
    """PRD §20 idempotency audit, 2026-08-28: audit_id used to be uuid.uuid4().hex[:12], so two
    concurrent execute_policy calls for the same (doc, policy) — a retried request racing the
    original, or two workers — could both pass the app-level doc_has_disposition check before
    either had inserted, producing two audit rows for what this route's own docstring promises is
    a single, idempotent outcome. The id is now derived from (doc_id, policy_id) alone, so the
    same pair always computes the same id and a race collides via ON CONFLICT(id) DO NOTHING
    instead of duplicating — this asserts the id itself is a pure, deterministic function of the
    pair, independent of when/how often it's computed."""
    rd, core, st = routed
    _seed_doc(st)
    pid = _make_tag_policy(rd, "tag legacy drive", requires_approval=False)

    rd.execute_policy(pid, _Req())
    audit = st.list_disposition_audit()
    assert len(audit) == 1
    first_id = audit[0]["id"]

    # Simulate a second, concurrent caller racing the first: it recomputes the same audit_id for
    # the same (doc, policy) pair before observing the first call's insert. Direct store call
    # (not another execute_policy) isolates the id-collision guarantee from the app-level
    # doc_has_disposition skip already covered by test_tag_policy_execute_writes_file_tags_idempotently.
    import hashlib
    racing_id = hashlib.sha256(f"policy_execute:{'drive:t1'}:{pid}".encode()).hexdigest()[:24]
    assert racing_id == first_id, "the id must be a pure function of (doc_id, policy_id)"
    st.create_disposition_audit(racing_id, doc_id="drive:t1", policy_id=pid,
                                action="tag", result="applied", detail="racing duplicate")

    audit_after = st.list_disposition_audit()
    assert len(audit_after) == 1, "a racing duplicate insert must collide, not add a second row"
    assert audit_after[0]["detail"] != "racing duplicate"   # the ON CONFLICT kept the original


def test_tag_policy_needs_no_drive_connection_on_execute(routed):
    # A non-Drive document, no x-drive-token header: archive/delete would 400 here,
    # but tag applies because it never calls Drive.
    rd, core, st = routed
    _seed_doc(st, doc_id="sp:x1", path="site/policy.docx", source="drive")
    pid = _make_tag_policy(rd, "tag any", requires_approval=False)
    summary = rd.execute_policy(pid, _Req())          # _Req() has no drive token
    assert summary["applied"] == 1
    assert st.list_file_tags("sp:x1", "site/policy.docx")


def test_tag_policy_writes_tags_only_on_approval(routed):
    rd, core, st = routed
    _seed_doc(st)
    pid = _make_tag_policy(rd, "tag gated", requires_approval=True)

    summary = rd.execute_policy(pid, _Req())
    assert summary["pending_approval"] == 1 and summary["applied"] == 0
    assert st.list_file_tags("drive:t1", "Reports/old.docx") == []   # nothing applied yet

    audit_id = st.list_disposition_audit(result="pending_approval")[0]["id"]
    rd.approve_disposition(audit_id, _Req())
    tags = st.list_file_tags("drive:t1", "Reports/old.docx")
    assert sorted(t["tag"] for t in tags) == ["legacy", "review"]
    assert all(t["rule_id"] == pid for t in tags)


def test_tag_policy_create_rejects_empty_tags(routed):
    from fastapi import HTTPException
    rd, core, st = routed
    body = rd.PolicyCreate(name="bad tag", match=[{"field": "source", "op": "eq", "value": "drive"}],
                           action="tag", action_config={"tags": []},
                           requires_approval=False, enabled=True)
    with pytest.raises(HTTPException) as ei:
        rd.create_policy(body, _Req())
    assert ei.value.status_code == 422
