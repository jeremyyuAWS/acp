"""Approving 684 archive candidates at once must not mean more than the reviewer meant.

PRD §8 permits grouped approval; §11 constrains it. The per-row route
(/disposition/approvals/{audit_id}/approve) is safe because a reviewer sees one file and
decides about that file. A batch route is where a review queue becomes dangerous, and every
rule below is one the PRD states as a way a bulk approval can widen silently:

  - it can re-expand ("approve everything matching X" resolves at EXECUTE time to whatever
    matches then, which is not what anyone reviewed);
  - it can be heterogeneous (the confirmation says "archive 40 under Retention v3" while the
    batch also carries a delete, or a different version of the rule);
  - it can be stale (the policy was edited after these rows were queued, so the explanation the
    reviewer read no longer describes the rule);
  - it can overrun a hold added DURING the review;
  - it can report a partial batch as a success.

The exemption re-check is the one worth reading the implementation for. Its first draft called
get_document(doc_id).get("lifecycle_status") — a column the documents table does not have. It
read None, compared it to "Exempted", and let everything through: a fail-OPEN check shaped
exactly like a fail-closed one, under a docstring promising the opposite. It now reads
scan_inventory, and test_an_exemption_added_during_review_wins is what would have caught it.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"
SCAN = "scan-batch-1"


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
    """Three archive candidates queued under retention v3, the way Discover leaves them."""
    st = isolated_store
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,%s,%s)",
                       (SCAN, OWNER, "discovered", "drive"))
    st.add_inventory(SCAN, [{"file": f"doc{i}.docx", "path": f"/estate/doc{i}.docx",
                             "owner": OWNER} for i in (1, 2, 3)])
    st.create_disposition_policy("retention", name="Retention", match="[]", action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE disposition_policy SET version=3 WHERE policy_id=%s",
                       ("retention",))
    st.bulk_create_disposition_audit([
        (f"aud{i}", f"scan:{SCAN}:doc{i}.docx", "retention", "archive", "pending_approval",
         "older than the cutoff", OWNER, 3) for i in (1, 2, 3)])
    for i in (1, 2, 3):
        st.set_lifecycle_status(SCAN, f"doc{i}.docx", "Archive Candidate",
                                rule_id="retention", reason="older than the cutoff")
    return st


def _approve(client, **over):
    body = {"audit_ids": ["aud1", "aud2", "aud3"], "policy_id": "retention",
            "policy_version": 3, "action": "archive"}
    body.update(over)
    return client.post("/disposition/approvals", json=body)


def test_a_homogeneous_batch_is_approved_and_reconciles(gated_client, queued):
    r = _approve(gated_client(OWNER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["approved"]) == ["aud1", "aud2", "aud3"]
    assert body["refused"] == [] and body["already_decided"] == []
    assert body["reconciled"] is True and body["submitted"] == 3
    # Recording a decision is not touching a file. The route says so and must keep saying so.
    assert body["executed"] is False
    assert queued.get_disposition_audit("aud1", owner=OWNER)["result"] == "approved"


def test_the_reason_reaches_every_audit_row(gated_client, queued):
    _approve(gated_client(OWNER), reason="Q3 retention sign-off")
    detail = queued.get_disposition_audit("aud2", owner=OWNER)["detail"]
    assert "Q3 retention sign-off" in detail and "retention v3" in detail


def test_a_mixed_action_batch_changes_nothing_at_all(gated_client, queued):
    """§8. A partially-applied heterogeneous batch is the worst outcome: the confirmation the
    reviewer read was true of some rows and the rest went through anyway."""
    queued.bulk_create_disposition_audit([
        ("audX", f"scan:{SCAN}:doc9.docx", "retention", "delete", "pending_approval",
         "much older", OWNER, 3)])
    r = _approve(gated_client(OWNER), audit_ids=["aud1", "audX"])
    assert r.status_code == 409
    assert "nothing was approved" in r.json()["detail"]
    assert queued.get_disposition_audit("aud1", owner=OWNER)["result"] == "pending_approval"


def test_a_batch_naming_a_superseded_policy_version_is_refused(gated_client, queued):
    """§11. Editing the rule after these rows were queued means the reviewer is approving an
    explanation that no longer describes it."""
    with queued._db.cursor() as cur:
        queued._db.execute(cur, "UPDATE disposition_policy SET version=4 WHERE policy_id=%s",
                           ("retention",))
    r = _approve(gated_client(OWNER))
    assert r.status_code == 409
    assert "now version 4" in r.json()["detail"]
    assert queued.get_disposition_audit("aud1", owner=OWNER)["result"] == "pending_approval"


def test_rows_queued_under_an_older_version_are_refused_as_a_group(gated_client, queued):
    queued.bulk_create_disposition_audit([
        ("audOld", f"scan:{SCAN}:doc8.docx", "retention", "archive", "pending_approval",
         "queued under v2", OWNER, 2)])
    r = _approve(gated_client(OWNER), audit_ids=["aud1", "audOld"])
    assert r.status_code == 409
    assert queued.get_disposition_audit("aud1", owner=OWNER)["result"] == "pending_approval"


def test_an_exemption_added_during_review_wins(gated_client, queued):
    """§11, fail-closed and re-checked immediately before the decision lands. This is the test
    that catches an exemption check reading a column its table does not have."""
    queued.set_lifecycle_status(SCAN, "doc2.docx", "Exempted", rule_id="retention",
                                reason="legal hold raised during review")
    r = _approve(gated_client(OWNER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["approved"]) == ["aud1", "aud3"]
    assert [x["audit_id"] for x in body["refused"]] == ["aud2"]
    assert "Exempted" in body["refused"][0]["why"]
    assert body["reconciled"] is True
    assert queued.get_disposition_audit("aud2", owner=OWNER)["result"] == "pending_approval"


def test_a_reviewers_override_is_not_overturned_by_a_batch(gated_client, queued):
    """A human already said "keep this". A batch must not quietly reverse an individual decision."""
    queued.override_lifecycle(SCAN, "doc3.docx", reason="still cited by the 2019 audit",
                              actor=OWNER)
    body = _approve(gated_client(OWNER)).json()
    assert sorted(body["approved"]) == ["aud1", "aud2"]
    assert [x["audit_id"] for x in body["refused"]] == ["aud3"]
    assert "overridden" in body["refused"][0]["why"]


def test_a_delete_batch_must_state_a_reason(gated_client, queued):
    """§8: every delete approval carries a mandatory reason."""
    queued.bulk_create_disposition_audit([
        ("audDel", f"scan:{SCAN}:doc1.docx", "retention", "delete", "pending_approval",
         "much older", OWNER, 3)])
    r = _approve(gated_client(OWNER), audit_ids=["audDel"], action="delete")
    assert r.status_code == 400 and "reason" in r.json()["detail"]
    r = _approve(gated_client(OWNER), audit_ids=["audDel"], action="delete",
                 reason="records schedule 7 expired")
    assert r.status_code == 200, r.text
    assert r.json()["approved"] == ["audDel"]


def test_resubmitting_a_batch_does_not_approve_anything_twice(gated_client, queued):
    """Idempotent on the row's own identity: a double-submitted batch reconciles as
    already_decided, never as a second approval."""
    first = _approve(gated_client(OWNER)).json()
    assert len(first["approved"]) == 3
    second = _approve(gated_client(OWNER)).json()
    assert second["approved"] == []
    assert sorted(x["audit_id"] for x in second["already_decided"]) == ["aud1", "aud2", "aud3"]
    assert second["reconciled"] is True


def test_an_unknown_id_is_refused_and_still_reconciles(gated_client, queued):
    body = _approve(gated_client(OWNER), audit_ids=["aud1", "nope"]).json()
    assert body["approved"] == ["aud1"]
    assert [x["audit_id"] for x in body["refused"]] == ["nope"]
    assert body["reconciled"] is True


def test_another_owners_rows_are_invisible_rather_than_approvable(gated_client, isolated_store):
    """The batch reader is owner-scoped. A foreign id must not be approvable, and must not
    silently succeed either — it comes back refused as not found."""
    isolated_store.create_disposition_policy("retention", name="Retention", match="[]",
                                             action="archive", action_config="{}",
                                             requires_approval=True, enabled=True,
                                             owner_email=OWNER)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE disposition_policy SET version=3 WHERE policy_id=%s",
                                   ("retention",))
    isolated_store.bulk_create_disposition_audit([
        ("audTheirs", "scan:other:doc.docx", "retention", "archive", "pending_approval",
         "theirs", OTHER, 3)])
    body = _approve(gated_client(OWNER), audit_ids=["audTheirs"]).json()
    assert body["approved"] == []
    assert body["refused"][0]["why"] == "not found for this owner"
    assert isolated_store.get_disposition_audit("audTheirs", owner=OTHER)["result"] == "pending_approval"


def test_a_non_owner_cannot_approve_in_bulk(gated_client, queued):
    r = _approve(gated_client(OTHER))
    assert r.status_code in (401, 403), r.status_code
    assert queued.get_disposition_audit("aud1", owner=OWNER)["result"] == "pending_approval"


def test_an_empty_batch_is_refused_rather_than_reported_as_success(gated_client, queued):
    r = _approve(gated_client(OWNER), audit_ids=[])
    assert r.status_code == 400


def test_a_row_from_another_code_path_is_refused_not_guessed_at(gated_client, queued):
    """Only the discover-lifecycle id shape can have its lifecycle state re-read. Anything else
    is refused with a pointer to the per-row route, rather than approved unchecked."""
    queued.bulk_create_disposition_audit([
        ("audDoc", "drive:abc123", "retention", "archive", "pending_approval",
         "from another path", OWNER, 3)])
    body = _approve(gated_client(OWNER), audit_ids=["audDoc"]).json()
    assert body["approved"] == []
    assert "individually" in body["refused"][0]["why"]
