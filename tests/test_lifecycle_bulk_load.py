"""Bulk-load path for lifecycle rule evaluation.

_evaluate_discover_lifecycle_rules now pre-loads all existing dispositions for a scan
in one query (get_scan_dispositions) and accumulates writes across the inventory loop,
flushing them as three bulk operations instead of N individual INSERT/UPDATE calls.

These tests verify:
  A. Store methods: get_scan_dispositions, bulk_add_file_tags, bulk_set_lifecycle_status,
     bulk_create_disposition_audit produce the same outcomes as their per-row equivalents.
  B. Handler behaviour: the bulk path produces identical lifecycle outcomes to what the
     per-file path used to produce — same statuses, same tags, same audit rows.
  C. Idempotency: re-running _evaluate_discover_lifecycle_rules via the bulk path adds
     no duplicate tags, statuses, or audit rows.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ── helpers ───────────────────────────────────────────────────────────────────

def _items():
    return [
        {"name": "old.docx", "id": "d-old", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Archive/old.docx", "parent_folder": "/Archive", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c-old"},
        {"name": "new.docx", "id": "d-new", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Current/new.docx", "parent_folder": "/Current", "owner": "cfo@x.com",
         "created_at": "2025-01-01T00:00:00+00:00", "source_modified": "2025-06-01T00:00:00+00:00",
         "size_kb": 12, "checksum": "c-new"},
    ]


def _policy(st, name, action, match, *, action_config=None, owner="admin@x.com"):
    pid = "p-" + name
    st.create_disposition_policy(
        pid, name=name, match=json.dumps(match), action=action,
        action_config=json.dumps(action_config or {}), requires_approval=False, enabled=True,
        owner_email=owner)
    return pid


def _wire(monkeypatch, st):
    import core, scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())


def _discover(scan_id="s1", user="admin@x.com"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": user},
                            {"scan_id": scan_id})


# ── A. store-level unit tests ─────────────────────────────────────────────────

def test_get_scan_dispositions_empty_when_none_exist(isolated_store):
    """Pre-load returns empty set when no dispositions have been recorded."""
    st = isolated_store
    seen = st.get_scan_dispositions("s-none")
    assert seen == set()


def test_get_scan_dispositions_returns_live_pairs(isolated_store):
    """Pre-load returns (doc_id, policy_id) for live outcomes only."""
    st = isolated_store
    st.create_disposition_audit("a1", doc_id="scan:s1:file.docx", policy_id="p1",
                                action="archive", result="pending_approval",
                                detail="reason", owner_email="x@x.com")
    # rejected row must NOT appear in the pre-load — it should be re-processed on re-run
    st.create_disposition_audit("a2", doc_id="scan:s1:other.docx", policy_id="p1",
                                action="archive", result="rejected",
                                detail="rejected", owner_email="x@x.com")
    # different scan must NOT bleed in
    st.create_disposition_audit("a3", doc_id="scan:s2:file.docx", policy_id="p1",
                                action="archive", result="pending_approval",
                                detail="reason", owner_email="x@x.com")

    seen = st.get_scan_dispositions("s1")
    assert ("scan:s1:file.docx", "p1") in seen
    assert ("scan:s1:other.docx", "p1") not in seen   # rejected — not live
    assert ("scan:s2:file.docx", "p1") not in seen    # different scan


def test_bulk_set_lifecycle_status(isolated_store):
    """bulk_set_lifecycle_status writes the same columns as set_lifecycle_status."""
    st = isolated_store
    st.init_scan_run("s1", "local", total=2,
                     started_at="2025-01-01T00:00:00Z", rubric_name="r", rubric_hash="h")
    st.add_inventory("s1", [
        {"file": "a.docx", "doc_class": "word", "size_kb": 10,
         "source_modified": "2020-01-01T00:00:00Z", "parent_folder": "/", "tags": [],
         "issues": [], "department": None, "sourceName": "local"},
        {"file": "b.docx", "doc_class": "word", "size_kb": 10,
         "source_modified": "2024-01-01T00:00:00Z", "parent_folder": "/", "tags": [],
         "issues": [], "department": None, "sourceName": "local"},
    ])
    st.bulk_set_lifecycle_status([
        ("s1", "a.docx", "Archive Candidate", "p-arc", "stale doc"),
    ])
    a_status = st.get_lifecycle_status("s1", "a.docx")
    assert a_status["lifecycle_status"] == "Archive Candidate"
    assert a_status["lifecycle_rule_id"] == "p-arc"
    assert a_status["lifecycle_reason"] == "stale doc"
    # b.docx untouched
    assert st.get_lifecycle_status("s1", "b.docx")["lifecycle_status"] == "Active"


def test_bulk_add_file_tags(isolated_store):
    """bulk_add_file_tags writes the same tags as add_file_tags."""
    st = isolated_store
    st.init_scan_run("s1", "local", total=1,
                     started_at="2025-01-01T00:00:00Z", rubric_name="r", rubric_hash="h")
    st.add_inventory("s1", [
        {"file": "a.docx", "doc_class": "word", "size_kb": 10,
         "source_modified": "2020-01-01T00:00:00Z", "parent_folder": "/", "tags": [],
         "issues": [], "department": None, "sourceName": "local"},
    ])
    st.bulk_add_file_tags([
        ("s1", "a.docx", "Stale", "system", "p-tag"),
        ("s1", "a.docx", "Review", "system", "p-tag"),
    ])
    tags = {t["tag"] for t in st.list_file_tags("s1", "a.docx")}
    assert tags == {"Stale", "Review"}


def test_bulk_create_disposition_audit(isolated_store):
    """bulk_create_disposition_audit inserts rows that get_disposition_audit can read back."""
    st = isolated_store
    st.bulk_create_disposition_audit([
        ("audit-x1", "scan:s1:a.docx", "p1", "archive",
         "pending_approval", "stale", "x@x.com"),
    ])
    row = st.get_disposition_audit("audit-x1")
    assert row is not None
    assert row["doc_id"] == "scan:s1:a.docx"
    assert row["result"] == "pending_approval"


# ── B. handler produces identical outcomes via bulk path ──────────────────────

def test_bulk_path_sets_archive_candidate(isolated_store, monkeypatch):
    """Archive rule still flags matching files via the bulk path."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover()

    old = st.get_lifecycle_status("s1", "old.docx")
    assert old["lifecycle_status"] == "Archive Candidate"
    assert st.get_lifecycle_status("s1", "new.docx")["lifecycle_status"] == "Active"


def test_bulk_path_applies_tags(isolated_store, monkeypatch):
    """Tag rule still writes system tags via the bulk path."""
    st = isolated_store
    _wire(monkeypatch, st)
    pid = _policy(st, "tag-archive-folder", "tag",
                  [{"field": "path", "op": "prefix", "value": "/Archive/"}],
                  action_config={"tags": ["Stale", "Review"]})
    _discover()

    tags = st.list_file_tags("s1", "old.docx")
    assert sorted(t["tag"] for t in tags) == ["Review", "Stale"]
    assert all(t["kind"] == "system" and t["rule_id"] == pid for t in tags)
    assert st.list_file_tags("s1", "new.docx") == []


def test_bulk_path_audit_row_recorded(isolated_store, monkeypatch):
    """Archive candidate produces a pending_approval audit row via the bulk path."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover()

    audit = st.list_disposition_audit(doc_id="scan:s1:old.docx")
    assert len(audit) == 1
    assert audit[0]["result"] == "pending_approval"
    assert audit[0]["action"] == "archive"


# ── C. idempotency via bulk path ──────────────────────────────────────────────

def test_bulk_path_rediscover_is_idempotent(isolated_store, monkeypatch):
    """Re-running Discover via the bulk path adds no duplicate tags or audit rows."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _policy(st, "tag-archive-folder", "tag",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"tags": ["Stale"]})

    _discover()
    _discover()  # second run — must be a no-op

    tags = st.list_file_tags("s1", "old.docx")
    assert len(tags) == 1  # not doubled

    audit = st.list_disposition_audit(doc_id="scan:s1:old.docx")
    assert len(audit) == 2  # one archive + one tag — not quadrupled
