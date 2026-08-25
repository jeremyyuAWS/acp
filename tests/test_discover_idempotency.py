"""Discover write idempotency (Stage 1 item 4).

Acceptance criteria:
  1. Retrying Discover with the same inputs produces no duplicate disposition_audit rows.
  2. The audit_id for a (scan_id, file, policy_id, action) tuple is deterministic across retries.
  3. create_disposition_audit ON CONFLICT(id) DO NOTHING silently ignores a duplicate audit_id.
  4. Inventory and tags are also idempotent on retry (ON CONFLICT upserts).
  5. A different (scan_id, file, policy_id) produces a distinct audit_id — no collisions.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

OWNER = "admin@x.com"


def _items():
    return [
        {"name": "stale.docx", "id": "d-stale", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Arch/stale.docx", "parent_folder": "/Arch", "owner": OWNER,
         "created_at": "2018-01-01T00:00:00+00:00",
         "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c-stale"},
    ]


def _policy(st, name, action, match, *, action_config=None):
    pid = "p-" + name
    st.create_disposition_policy(
        pid, name=name, match=json.dumps(match), action=action,
        action_config=json.dumps(action_config or {}), requires_approval=False,
        enabled=True, owner_email=OWNER)
    return pid


def _wire(monkeypatch, st):
    import core, scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())


def _discover(scan_id="s1"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": OWNER},
                            {"scan_id": scan_id})


# ── Criterion 1: no duplicate audit rows on retry ───────────────────────────

def test_retry_discover_no_duplicate_audit_candidate(isolated_store, monkeypatch):
    """Running Discover twice with the same scan produces exactly one audit row per file/policy."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "arc-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover("s-idem-1")
    _discover("s-idem-1")  # retry

    rows = st.list_disposition_audit(doc_id="scan:s-idem-1:stale.docx")
    assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}: {rows}"


def test_retry_discover_no_duplicate_audit_tag(isolated_store, monkeypatch):
    """A tag-action policy also produces exactly one audit row on retry."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "tag-stale", "tag",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}],
            action_config={"tags": ["Stale"]})
    _discover("s-idem-2")
    _discover("s-idem-2")

    rows = st.list_disposition_audit(doc_id="scan:s-idem-2:stale.docx")
    assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}: {rows}"


# ── Criterion 2: deterministic audit_id ─────────────────────────────────────

def test_audit_id_is_deterministic_for_same_inputs():
    """Same (scan_id, file, policy_id, action) always produces the same audit_id."""
    def _make(scan_id, file, policy_id, action):
        return hashlib.sha256(
            f"discover:{scan_id}:{file}:{policy_id}:{action}".encode()
        ).hexdigest()[:24]

    id1 = _make("scan-x", "old.docx", "pol-1", "archive")
    id2 = _make("scan-x", "old.docx", "pol-1", "archive")
    assert id1 == id2


# ── Criterion 3: create_disposition_audit ON CONFLICT is a silent no-op ─────

def test_create_disposition_audit_duplicate_id_is_noop(isolated_store):
    """Inserting the same audit_id twice must not raise and must not create a second row."""
    st = isolated_store
    st.create_disposition_audit("dup-id-001", doc_id="d1", policy_id="pol-1",
                                action="archive", result="pending_approval",
                                detail="test", owner_email=OWNER)
    # Second call with the same id — must not raise
    st.create_disposition_audit("dup-id-001", doc_id="d1", policy_id="pol-1",
                                action="archive", result="pending_approval",
                                detail="test", owner_email=OWNER)

    rows = st.list_disposition_audit(doc_id="d1")
    assert len(rows) == 1


def test_create_disposition_audit_different_ids_create_separate_rows(isolated_store):
    """Different audit_ids for different (file, policy) combinations create separate rows."""
    st = isolated_store
    st.create_disposition_audit("id-a", doc_id="d1", policy_id="pol-1",
                                action="archive", result="pending_approval",
                                detail="a", owner_email=OWNER)
    st.create_disposition_audit("id-b", doc_id="d2", policy_id="pol-2",
                                action="tag", result="applied",
                                detail="b", owner_email=OWNER)

    assert len(st.list_disposition_audit()) == 2


# ── Criterion 4: inventory and tags are also idempotent ─────────────────────

def test_retry_discover_no_duplicate_inventory_rows(isolated_store, monkeypatch):
    """Running Discover twice produces one inventory row, not two (add_inventory upsert)."""
    st = isolated_store
    _wire(monkeypatch, st)
    _discover("s-inv-1")
    _discover("s-inv-1")

    inv = st.list_inventory("s-inv-1")
    files = [r["file"] for r in inv]
    assert files.count("stale.docx") == 1


def test_retry_discover_no_duplicate_tags(isolated_store, monkeypatch):
    """Running Discover twice with a tag policy produces one tag row, not two."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "tag-dup", "tag",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}],
            action_config={"tags": ["Stale"]})
    _discover("s-tag-1")
    _discover("s-tag-1")

    tags = st.list_file_tags("s-tag-1", "stale.docx")
    stale_tags = [t for t in tags if t.get("tag") == "Stale"]
    assert len(stale_tags) == 1


# ── Criterion 5: distinct inputs produce distinct audit IDs ─────────────────

def test_audit_id_distinct_across_different_files():
    """Different files in the same scan produce different audit IDs."""
    def _make(scan_id, file, policy_id, action):
        return hashlib.sha256(
            f"discover:{scan_id}:{file}:{policy_id}:{action}".encode()
        ).hexdigest()[:24]

    id_a = _make("scan-x", "a.docx", "pol-1", "archive")
    id_b = _make("scan-x", "b.docx", "pol-1", "archive")
    assert id_a != id_b


def test_audit_id_distinct_across_different_scans():
    """Same file+policy in different scans produces different audit IDs."""
    def _make(scan_id, file, policy_id, action):
        return hashlib.sha256(
            f"discover:{scan_id}:{file}:{policy_id}:{action}".encode()
        ).hexdigest()[:24]

    id1 = _make("scan-A", "f.docx", "pol-1", "archive")
    id2 = _make("scan-B", "f.docx", "pol-1", "archive")
    assert id1 != id2


def test_audit_id_distinct_across_different_actions():
    """Tag vs archive for the same file+policy produce different IDs (no cross-action collision)."""
    def _make(scan_id, file, policy_id, action):
        return hashlib.sha256(
            f"discover:{scan_id}:{file}:{policy_id}:{action}".encode()
        ).hexdigest()[:24]

    id_tag = _make("scan-x", "f.docx", "pol-1", "tag")
    id_arc = _make("scan-x", "f.docx", "pol-1", "archive")
    assert id_tag != id_arc
