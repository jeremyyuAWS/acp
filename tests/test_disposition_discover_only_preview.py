"""A rule preview (and the conflicts report) must see a Discover-only estate, not just an
assessed one.

THE DEFECT (found live 2026-08-21): on a fresh account that had only ever run Discover — never
Assess — a lifecycle rule's preview always reported "would_match: 0", no matter how broad the
rule. Even an unconditioned-equivalent rule ("older than 1 day", which should match virtually
every real file) previewed as matching nothing against a real 385-file estate.

Root cause: `_preview`/`list_conflicts` (api/routes/disposition.py) read
`store.list_all_documents()` — the `documents` table, written ONLY by Assess's
`upsert_document`. Actual Discover-time tagging (`handlers._evaluate_discover_lifecycle_rules`)
runs against `scan_inventory` instead, via `disposition.matches()` — a completely different
table the preview never looked at. A Discover-only scan therefore correctly TAGGED its
`scan_inventory` rows, while the preview (and the enable-confirmation dialog's count, #611, which
shares the same evaluator) kept reporting zero regardless.

`store.list_pending_disposition_candidates` is the fix: it reads `scan_inventory` for scans still
`status='discovered'`, reshaped like a `documents` row. Once Assess runs, a scan's files become
real `documents` rows and its status moves off 'discovered' — so a file is covered by exactly one
of `list_all_documents` and this method, never both.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "devamovate@gmail.com"


def _discovered_scan(st, sid, owner, files, source="drive"):
    """A scan in exactly the state ADR 0020 leaves a Discover-only run in: listed, inventoried,
    not assessed. `files` is a list of scan_inventory row dicts (file + whatever else matters)."""
    st.init_scan_run(sid, source, len(files), "2026-08-19T09:00:00+00:00", "acp", "hash1",
                     owner=owner, status="discovered")
    st.add_inventory(sid, files)


def _assessed_scan(st, sid, owner, files, source="drive"):
    """A scan that HAS been assessed — status moves off 'discovered', and every file also gets a
    real `documents` row (what Assess actually does via upsert_document)."""
    st.init_scan_run(sid, source, len(files), "2026-08-19T09:00:00+00:00", "acp", "hash1",
                     owner=owner, status="running")
    for f in files:
        st.upsert_document(f"{sid}:{f['file']}", source=source, path=f.get("path"),
                           content_hash=None, owner=owner,
                           created_at=f.get("created_at", "2026-01-01T00:00:00+00:00"),
                           last_seen="2026-08-19T00:00:00+00:00", triage_score=0,
                           triage_rationale="", owner_email=owner)


# ── Store level ──────────────────────────────────────────────────────────────────────────────

def test_returns_inventory_rows_for_a_still_discovered_scan(isolated_store):
    st = isolated_store
    _discovered_scan(st, "s1", OWNER, [
        {"file": "a.docx", "path": "Finance/a.docx", "doc_class": "document", "size_kb": 40},
    ])
    rows = st.list_pending_disposition_candidates(owner=OWNER)
    assert len(rows) == 1
    row = rows[0]
    assert row["doc_id"] == "scan:s1:a.docx"
    assert row["path"] == "Finance/a.docx"
    assert row["doc_class"] == "document"
    assert row["size_kb"] == 40
    assert row["source"] == "drive"


def test_excludes_a_scan_that_has_moved_past_discovered(isolated_store):
    """Once Assess runs, `set_scan_status`/init_scan_run('running') moves the scan off
    'discovered' — its inventory must stop showing up here, since its files now have real
    `documents` rows instead (see test_no_double_counting_across_the_two_sources below)."""
    st = isolated_store
    _assessed_scan(st, "s1", OWNER, [{"file": "a.docx", "path": "Finance/a.docx"}])
    assert st.list_pending_disposition_candidates(owner=OWNER) == []


def test_owner_scoped(isolated_store):
    st = isolated_store
    _discovered_scan(st, "s1", OWNER, [{"file": "a.docx", "path": "a.docx"}])
    _discovered_scan(st, "s2", OTHER, [{"file": "b.docx", "path": "b.docx"}])
    mine = st.list_pending_disposition_candidates(owner=OWNER)
    assert [r["doc_id"] for r in mine] == ["scan:s1:a.docx"]


def test_empty_without_any_discovered_scans(isolated_store):
    assert isolated_store.list_pending_disposition_candidates(owner=OWNER) == []


def test_no_double_counting_across_the_two_sources(isolated_store):
    """The core invariant the fix depends on: a file is in exactly one of list_all_documents()
    and list_pending_disposition_candidates() at a time, so a caller can simply concatenate them
    without deduplicating."""
    st = isolated_store
    _discovered_scan(st, "s1", OWNER, [{"file": "a.docx", "path": "a.docx"}])
    _assessed_scan(st, "s2", OWNER, [{"file": "b.docx", "path": "b.docx"}])
    pending = {r["doc_id"] for r in st.list_pending_disposition_candidates(owner=OWNER)}
    assessed = {d["doc_id"] for d in st.list_all_documents(owner=OWNER)}
    assert pending == {"scan:s1:a.docx"}
    assert assessed == {"s2:b.docx"}
    assert pending.isdisjoint(assessed)


# ── Route level ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e == OWNER)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {OWNER}"})
    return client, isolated_store


def _policy(st, policy_id, name, *, action, match, enabled=True, action_config=None):
    st.create_disposition_policy(policy_id, name=name, match=json.dumps(match), action=action,
                                 action_config=json.dumps(action_config or {}),
                                 requires_approval=True, enabled=enabled, owner_email=OWNER)


def test_preview_sees_a_discover_only_estate(client):
    """The exact regression: a rule broad enough to match virtually everything must not preview
    as zero just because nothing has been assessed yet."""
    c, st = client
    _discovered_scan(st, "s1", OWNER, [
        {"file": "a.docx", "path": "Finance/2019/a.docx"},
        {"file": "b.docx", "path": "Finance/2019/b.docx"},
        {"file": "c.docx", "path": "HR/c.docx"},
    ])
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    body = c.post("/disposition/policies/p1/preview").json()
    assert body["would_match"] == 2
    assert body["total"] == 3


def test_preview_is_a_real_zero_when_nothing_matches(client):
    """The fix must not make everything match — it only widens WHERE candidates come from."""
    c, st = client
    _discovered_scan(st, "s1", OWNER, [{"file": "c.docx", "path": "HR/c.docx"}])
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    body = c.post("/disposition/policies/p1/preview").json()
    assert body["would_match"] == 0
    assert body["total"] == 1


def test_preview_combines_assessed_and_discover_only_without_duplicating(client):
    c, st = client
    _assessed_scan(st, "s1", OWNER, [{"file": "a.docx", "path": "Finance/a.docx"}])
    _discovered_scan(st, "s2", OWNER, [{"file": "b.docx", "path": "Finance/b.docx"}])
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    body = c.post("/disposition/policies/p1/preview").json()
    assert body["would_match"] == 2
    assert body["total"] == 2


def test_conflicts_sees_a_discover_only_estate_too(client):
    c, st = client
    _discovered_scan(st, "s1", OWNER, [{"file": "a.docx", "path": "Finance/a.docx"}])
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    _policy(st, "p2", "delete finance", action="delete",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    body = c.get("/disposition/policies/conflicts").json()
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["doc_id"] == "scan:s1:a.docx"


def test_conflicts_still_scoped_to_the_caller_tenant(client):
    c, st = client
    _discovered_scan(st, "s1", OTHER, [{"file": "a.docx", "path": "Finance/a.docx"}])
    st.create_disposition_policy("t1", name="a", match=json.dumps(
        [{"field": "path", "op": "prefix", "value": "Finance/"}]),
        action="archive", action_config="{}", requires_approval=True, enabled=True,
        owner_email=OTHER)
    st.create_disposition_policy("t2", name="b", match=json.dumps(
        [{"field": "path", "op": "prefix", "value": "Finance/"}]),
        action="delete", action_config="{}", requires_approval=True, enabled=True,
        owner_email=OTHER)
    assert c.get("/disposition/policies/conflicts").json() == {"conflicts": []}
