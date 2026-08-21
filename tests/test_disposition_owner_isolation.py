"""Lifecycle rules are per-tenant, not global shared records.

THE DEFECT (reported 2026-08-21): "lifecycle rules currently behave like global shared records,
so rules created by the demo account can appear in your workflow." Two things made this true:

  1. `disposition_policy` / `disposition_audit` shipped with NO ownership column at all — every
     signed-in user saw and could toggle/execute every OTHER tenant's rules.
  2. Even the one caller that already had the right owner in scope —
     `handlers._evaluate_discover_lifecycle_rules(scan_id, source, actor)` — fetched EVERY
     enabled policy regardless of `actor`, so a demo-account rule silently flagged files during
     a real user's Discover.

Fixed by adding `owner_email` to both tables (NULL-excluded, same pattern as
`documents.owner_email`) and scoping every read/write through it — store methods take an
`owner` param, routes derive it via `_owner(request)`, and the discover-time evaluator now
passes its already-known `actor` through instead of dropping it on the floor.

These tests pin the isolation itself, not the disposition feature's existing behaviour (that is
covered by test_disposition_policy_update.py, test_disposition_execute.py, etc.) — the question
here is specifically "can tenant A see or act on tenant B's rules."
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

MATCH = [{"field": "path", "op": "prefix", "value": "/Finance/"}]


# ── Store level: owner scoping + NULL exclusion ────────────────────────────────────────────────

def test_list_disposition_policies_excludes_other_owners(isolated_store):
    st = isolated_store
    st.create_disposition_policy("p-mine", name="mine", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=True, enabled=False, owner_email=OWNER)
    st.create_disposition_policy("p-theirs", name="theirs", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=True, enabled=False, owner_email=OTHER)

    mine = st.list_disposition_policies(owner=OWNER)
    assert [p["policy_id"] for p in mine] == ["p-mine"]


def test_a_row_with_no_owner_email_is_excluded_not_wildcarded(isolated_store):
    """Pre-migration rows (owner_email NULL) must not become visible to everybody just because
    nobody claims them — same NULL-exclusion philosophy as list_all_documents."""
    st = isolated_store
    st.create_disposition_policy("p-legacy", name="legacy", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=True, enabled=False)  # owner_email omitted -> NULL
    assert st.list_disposition_policies(owner=OWNER) == []
    assert st.list_disposition_policies() == [st.get_disposition_policy("p-legacy")]


def test_get_disposition_policy_404_shape_for_a_foreign_id(isolated_store):
    """Same shape as get_scan(sid, owner=...): a foreign policy_id returns None (the route turns
    that into 404), not the other tenant's row."""
    st = isolated_store
    st.create_disposition_policy("p-theirs", name="theirs", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=True, enabled=False, owner_email=OTHER)
    assert st.get_disposition_policy("p-theirs", owner=OWNER) is None
    assert st.get_disposition_policy("p-theirs", owner=OTHER) is not None


def test_disposition_audit_is_scoped_the_same_way(isolated_store):
    st = isolated_store
    st.create_disposition_audit("a-mine", doc_id="d1", policy_id="p1", action="archive",
                                result="applied", detail="x", owner_email=OWNER)
    st.create_disposition_audit("a-theirs", doc_id="d2", policy_id="p2", action="archive",
                                result="applied", detail="y", owner_email=OTHER)

    assert [a["id"] for a in st.list_disposition_audit(owner=OWNER)] == ["a-mine"]
    assert st.get_disposition_audit("a-theirs", owner=OWNER) is None
    assert st.get_disposition_audit("a-theirs", owner=OTHER) is not None


# ── Route level: two signed-in tenants never see each other's rules ────────────────────────────

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_foreign_scan_404.py's fixture: the real gate, stamping
    request.state.user_email from a fake token=email map so a test can sign in as anybody."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, OTHER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_a_policy_created_by_one_tenant_is_invisible_to_the_other(gated_client):
    c = gated_client(OWNER)
    pid = c.post("/disposition/policies",
                 json={"name": "archive stale finance", "match": MATCH,
                       "action": "archive"}).json()["policy_id"]

    assert [p["policy_id"] for p in c.get("/disposition/policies").json()] == [pid]
    assert gated_client(OTHER).get("/disposition/policies").json() == []


def test_a_foreign_policy_id_404s_not_leaks(gated_client):
    """The demo-account-rules-leaking-into-my-workflow report, at the route a person would
    actually hit: reading, previewing, enabling, editing, or executing someone else's rule id."""
    pid = gated_client(OWNER).post(
        "/disposition/policies",
        json={"name": "x", "match": MATCH, "action": "archive"}).json()["policy_id"]

    other = gated_client(OTHER)
    assert other.post(f"/disposition/policies/{pid}/preview").status_code == 404
    assert other.put(f"/disposition/policies/{pid}/enabled?enabled=true").status_code == 404
    assert other.put(f"/disposition/policies/{pid}", json={"name": "renamed"}).status_code == 404
    # execute is owner-only (_require_owner) regardless of policy ownership — OTHER is an
    # allowed non-owner in this fixture, so this 403s on the destructive-action gate before the
    # owner_email scoping is even reached. Real cross-tenant coverage for execute is
    # test_the_approval_queue_and_audit_trail_are_per_tenant's approve/reject 404s below.
    assert other.post(f"/disposition/policies/{pid}/execute").status_code == 403


def test_the_approval_queue_and_audit_trail_are_per_tenant(gated_client, isolated_store):
    st = isolated_store
    st.create_disposition_policy("p1", name="mine", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    st.create_disposition_audit("a1", doc_id="d1", policy_id="p1", action="archive",
                                result="pending_approval", detail="queued", owner_email=OWNER)
    st.create_disposition_policy("p2", name="theirs", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OTHER)
    st.create_disposition_audit("a2", doc_id="d2", policy_id="p2", action="archive",
                                result="pending_approval", detail="queued", owner_email=OTHER)

    assert [r["id"] for r in gated_client(OWNER).get("/disposition/approvals").json()] == ["a1"]
    assert [r["id"] for r in gated_client(OTHER).get("/disposition/approvals").json()] == ["a2"]
    assert [r["id"] for r in gated_client(OWNER).get("/disposition/audit").json()] == ["a1"]

    # reject is admin-gated (open-access model: any signed-in allowed user passes), so OTHER
    # reaches the owner_email-scoped lookup and 404s there — the isolation this test is for.
    assert gated_client(OTHER).post("/disposition/approvals/a1/reject").status_code == 404
    # approve is separately owner-only (_require_owner, the single protected OWNER_EMAIL) — OTHER
    # 403s on that gate before ownership is even checked, same as execute above.
    assert gated_client(OTHER).post("/disposition/approvals/a1/approve").status_code == 403


# ── The actual reported symptom: a demo-account rule leaking into a real Discover run ──────────

def test_discover_ignores_a_rule_owned_by_a_different_tenant(isolated_store, monkeypatch):
    """The root cause, reproduced directly: handlers._evaluate_discover_lifecycle_rules already
    received the scan's owner as `actor` and still fetched every tenant's enabled policies. A
    'demo'-owned archive rule must not flag files discovered by a real, different user."""
    import core
    import scanner
    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: [
        {"name": "ledger.docx", "id": "d1", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Finance/ledger.docx", "parent_folder": "/Finance", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c1"},
    ])

    st.create_disposition_policy("p-demo", name="demo's rule", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=False, enabled=True, owner_email="demo")

    import handlers
    handlers._scan_discover({"scan_id": "s1", "source": "local", "user": OWNER}, {"scan_id": "s1"})

    status = st.get_lifecycle_status("s1", "ledger.docx")
    assert (status or {}).get("lifecycle_status", "Active") == "Active", (
        "a rule owned by a different tenant ('demo') must not flag this file just because it "
        "matched — it belongs to somebody else's workflow"
    )
    assert st.list_disposition_audit(owner=OWNER) == []


def test_discover_still_applies_the_actors_own_rule(isolated_store, monkeypatch):
    """The contrast that proves the fix scopes rather than blanket-disables lifecycle rules."""
    import core
    import scanner
    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: [
        {"name": "ledger.docx", "id": "d1", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Finance/ledger.docx", "parent_folder": "/Finance", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c1"},
    ])

    st.create_disposition_policy("p-mine", name="my rule", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=False, enabled=True, owner_email=OWNER)

    import handlers
    handlers._scan_discover({"scan_id": "s1", "source": "local", "user": OWNER}, {"scan_id": "s1"})

    status = st.get_lifecycle_status("s1", "ledger.docx")
    assert (status or {}).get("lifecycle_status") == "Archive Candidate"
