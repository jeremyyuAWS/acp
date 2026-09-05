"""Approving a lifecycle candidate must not record that the document vanished.

THE DEFECT, measured before it was fixed. POST /disposition/approvals/{id}/approve defaults to
execute=true. On a Discover-lifecycle candidate it returned:

    HTTP 410 {"detail":"document no longer exists"}
    audit row: result='failed', detail='document no longer exists'

The file existed. The two subsystems key documents differently — the lifecycle evaluator stamps
`scan:{scan_id}:{file}` (handlers.py), while this governance layer keys on `drive:{id}` /
`{source}:{hash}` (documents.resolve_doc_id) — and list_all_documents holds none of the former.
So the lookup missed and the route concluded the document was gone.

Only the first of the three consequences is cosmetic:

  1. the stated reason is false;
  2. the reviewer's decision is DESTROYED — the pending row is consumed, so the approval has to
     be given again, and a queue that loses decisions stops being trusted;
  3. the append-only disposition_audit, which is the record a compliance officer relies on,
     now asserts that a document which exists did not.

The fix records the decision without executing — what execute=false already does, and what the
route's own docstring calls "the honest half of the operation". It is deliberately narrow: a
genuinely deleted Drive-backed document must still report that it no longer exists.

SINCE EXECUTION LANDED, this file pins the half of that behaviour that survives it. A lifecycle
candidate WITH a drive_file_id is now executed (see test_lifecycle_execution.py); the fixture
here gives its inventory row none, on purpose, because "not Drive-backed" is the case that still
has nothing to execute and must still record the decision rather than destroy it. The stated
reason moved with the truth: the blocker is no longer "not represented in the governance layer",
which is now resolvable, but that this particular row has no file id any connector could act on.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
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


@pytest.fixture()
def queued(isolated_store):
    st = isolated_store
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,%s,%s)",
                       ("s1", OWNER, "discovered", "drive"))
    # NO drive_file_id, deliberately: this is the candidate that cannot be executed even now,
    # and the record-only outcome below is its contract rather than a stage everything passes
    # through. A row WITH one is executed — test_lifecycle_execution.py covers that.
    st.add_inventory("s1", [{"file": "a.docx", "path": "/estate/a.docx", "owner": OWNER}])
    st.create_disposition_policy("retention", name="Retention", match="[]", action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    st.bulk_create_disposition_audit([
        ("aud-lifecycle", "scan:s1:a.docx", "retention", "archive", "pending_approval",
         "older than the cutoff", OWNER, 1),
        # A governance-layer row for a document that really is gone — the case whose existing
        # behaviour must survive this fix untouched.
        ("aud-vanished", "drive:deadbeef", "retention", "archive", "pending_approval",
         "older than the cutoff", OWNER, 1),
    ])
    return st


def test_a_lifecycle_approval_is_not_recorded_as_a_missing_document(gated_client, queued):
    """THE regression, in the audit row rather than the status code — the status code is the
    part nobody reads six months later."""
    r = gated_client(OWNER).post("/disposition/approvals/aud-lifecycle/approve?execute=true")
    assert r.status_code == 200, r.text

    row = queued.get_disposition_audit("aud-lifecycle", owner=OWNER)
    assert row["result"] == "approved", f"the approval was recorded as {row['result']!r}"
    assert "no longer exists" not in (row["detail"] or ""), (
        "the audit still asserts that a document which exists did not")
    assert "not executed" in row["detail"]


def test_the_reviewers_decision_survives(gated_client, queued):
    """The decision was destroyed before: the pending row was consumed and marked failed, so the
    approval had to be given again. 'approved' is a live outcome, so it is also not re-proposed."""
    gated_client(OWNER).post("/disposition/approvals/aud-lifecycle/approve?execute=true")
    row = queued.get_disposition_audit("aud-lifecycle", owner=OWNER)
    assert row["result"] not in ("failed", "pending_approval")


def test_the_response_says_plainly_that_nothing_was_executed(gated_client, queued):
    """The caller asked for execute=true and did not get it. A response identical to a real
    execution would be the same lie in a politer form.

    The REASON has to keep pace with what is actually true, which is the part that rots quietly:
    "no governance-layer document" described a real blocker until the resolution existed, and
    repeating it afterwards would send a reader looking for a gap that had been closed."""
    body = gated_client(OWNER).post("/disposition/approvals/aud-lifecycle/approve?execute=true").json()
    assert body["executed"] is False
    assert "no Drive file id" in body["why_not_executed"]
    assert "governance-layer" not in body["why_not_executed"], (
        "the stated reason still names a blocker that no longer applies")


def test_no_source_action_is_attempted(gated_client, queued, monkeypatch):
    """Recorded, not executed — so execute_action must not be reached at all. Without this the
    test above passes on a route that tried to touch Drive and merely failed quietly.

    Still true with execution shipped, and it is the assertion that says why: a row with no Drive
    id does not reach the connector at all, rather than reaching it and being turned away."""
    import disposition
    called = {"n": 0}
    real = disposition.execute_action
    monkeypatch.setattr(disposition, "execute_action",
                        lambda *a, **k: (called.__setitem__("n", called["n"] + 1), real(*a, **k))[1])
    gated_client(OWNER).post("/disposition/approvals/aud-lifecycle/approve?execute=true")
    assert called["n"] == 0, "a source action was attempted for a lifecycle candidate"


def test_a_genuinely_missing_document_still_reports_that_it_is_gone(gated_client, queued):
    """The fix is narrow ON PURPOSE. A Drive-backed document that really has been deleted must
    keep saying so — that is true, useful, and a broader rule would swallow it."""
    r = gated_client(OWNER).post("/disposition/approvals/aud-vanished/approve?execute=true")
    assert r.status_code == 410
    assert r.json()["detail"] == "document no longer exists"
    row = queued.get_disposition_audit("aud-vanished", owner=OWNER)
    assert row["result"] == "failed"
    assert row["detail"] == "document no longer exists"


def test_record_only_approval_is_unchanged(gated_client, queued):
    """execute=false already did the honest thing and must keep doing exactly it."""
    r = gated_client(OWNER).post("/disposition/approvals/aud-lifecycle/approve?execute=false")
    assert r.status_code == 200
    row = queued.get_disposition_audit("aud-lifecycle", owner=OWNER)
    assert row["result"] == "approved"
    assert "file not touched" in row["detail"] or "not executed" in row["detail"]


def test_a_non_owner_still_cannot_approve(gated_client, queued):
    r = gated_client(OTHER).post("/disposition/approvals/aud-lifecycle/approve?execute=true")
    assert r.status_code in (401, 403)
    assert queued.get_disposition_audit("aud-lifecycle", owner=OWNER)["result"] == "pending_approval"


def test_the_lifecycle_id_predicate_is_a_positive_test(gated_client):
    """Not "absent from the documents table" — that would swallow the genuinely-deleted case
    this fix deliberately preserves."""
    from routes.disposition import _is_lifecycle_doc_id
    assert _is_lifecycle_doc_id("scan:s1:a.docx") is True
    assert _is_lifecycle_doc_id("drive:abc123") is False
    assert _is_lifecycle_doc_id("sharepoint:deadbeef") is False
    assert _is_lifecycle_doc_id(None) is False
    assert _is_lifecycle_doc_id("") is False
