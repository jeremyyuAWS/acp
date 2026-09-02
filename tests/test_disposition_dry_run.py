"""What approving a batch WOULD do, without doing any of it (PRD §7.4's source-effect preview).

This is the safe half of making Discover-lifecycle candidates executable. Those candidates are
keyed `scan:{scan_id}:{file}` while the governance layer keys on `drive:{id}`, so nothing can
act on them today (#1182 keeps them record-only). The drive_file_id that would bridge the two
has been sitting on the inventory row the whole time; this resolves it in the one code path that
CANNOT act, so the gap becomes visible per row — "this one could be archived, that one has no
Drive id and never could" — before anybody authorises anything.

TWO PROPERTIES, and the tests exist for them rather than for the payload shape:

  1. It writes nothing. A dry run that can mutate is not a dry run, so the absence is asserted:
     no audit row moves, and disposition.execute_action is never reached.
  2. It is validated by the SAME rules as the approval it previews. A plan produced by a second
     copy of those rules drifts from what approval accepts, and the drift is invisible — it
     would show a batch that is then refused, or call one safe that is not.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"
SCAN = "scan-plan-1"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "cid", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda t: t or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, OTHER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.fixture()
def queued(isolated_store):
    """Three archive candidates: one Drive-backed, one with no Drive id, one exempt."""
    st = isolated_store
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,%s,%s)",
                       (SCAN, OWNER, "discovered", "drive"))
    st.add_inventory(SCAN, [
        {"file": "a.docx", "path": "/estate/a.docx", "owner": OWNER, "drive_file_id": "fid-a"},
        {"file": "b.docx", "path": "/estate/b.docx", "owner": OWNER},          # no Drive id
        {"file": "c.docx", "path": "/estate/c.docx", "owner": OWNER, "drive_file_id": "fid-c"},
    ])
    st.create_disposition_policy("retention", name="Retention", match="[]", action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE disposition_policy SET version=3 WHERE policy_id=%s",
                       ("retention",))
    st.bulk_create_disposition_audit([
        (f"aud-{f}", f"scan:{SCAN}:{f}.docx", "retention", "archive", "pending_approval",
         "older than the cutoff", OWNER, 3) for f in ("a", "b", "c")])
    for f in ("a", "b", "c"):
        st.set_lifecycle_status(SCAN, f"{f}.docx", "Archive Candidate",
                                rule_id="retention", reason="older than the cutoff")
    return st


def _plan(client, **over):
    body = {"audit_ids": ["aud-a", "aud-b", "aud-c"], "policy_id": "retention",
            "policy_version": 3, "action": "archive"}
    body.update(over)
    return client.post("/disposition/approvals/plan", json=body)


def test_the_plan_route_is_reachable_and_says_it_is_a_dry_run(gated_client, queued):
    """/approvals/plan sits beside /approvals/{audit_id}/approve; the payload states dry_run so a
    caller cannot mistake it for a receipt of something that happened."""
    r = _plan(gated_client(OWNER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True and body["executed"] is False
    assert body["planned"] == 3


def test_it_writes_nothing(gated_client, queued):
    """THE property. Every row stays exactly as it was."""
    before = {a: queued.get_disposition_audit(a, owner=OWNER)["result"]
              for a in ("aud-a", "aud-b", "aud-c")}
    _plan(gated_client(OWNER))
    after = {a: queued.get_disposition_audit(a, owner=OWNER)["result"]
             for a in ("aud-a", "aud-b", "aud-c")}
    assert after == before == {"aud-a": "pending_approval", "aud-b": "pending_approval",
                               "aud-c": "pending_approval"}


def test_it_never_reaches_execute_action(gated_client, queued, monkeypatch):
    """Without this, the test above passes on a route that tried to act and merely failed."""
    import disposition
    monkeypatch.setattr(disposition, "execute_action",
                        lambda *a, **k: pytest.fail("a dry run reached execute_action"))
    assert _plan(gated_client(OWNER)).status_code == 200


def test_it_resolves_the_drive_id_a_lifecycle_candidate_would_act_on(gated_client, queued):
    """The identifier bridge, exercised where it cannot do harm."""
    rows = {p["audit_id"]: p for p in _plan(gated_client(OWNER)).json()["plan"]}
    assert rows["aud-a"]["drive_file_id"] == "fid-a"
    assert rows["aud-a"]["blocked"] is None
    assert "move the file out of its current folder" in rows["aud-a"]["will"]
    assert "Archived" in rows["aud-a"]["target"] or "folder" in rows["aud-a"]["target"]


def test_a_file_with_no_drive_id_is_blocked_and_says_why(gated_client, queued):
    """Visible per row, before anybody authorises anything — rather than discovered at execution
    as a failure on a batch the reviewer already approved."""
    rows = {p["audit_id"]: p for p in _plan(gated_client(OWNER)).json()["plan"]}
    assert rows["aud-b"]["drive_file_id"] is None
    assert "unsupported source" in rows["aud-b"]["blocked"]
    assert rows["aud-b"]["will"] is None


def test_an_exempt_row_is_blocked_in_the_plan_too(gated_client, queued):
    queued.set_lifecycle_status(SCAN, "c.docx", "Exempted", rule_id="retention",
                                reason="legal hold")
    rows = {p["audit_id"]: p for p in _plan(gated_client(OWNER)).json()["plan"]}
    assert "Exempted" in rows["aud-c"]["blocked"]


def test_the_counts_reconcile(gated_client, queued):
    body = _plan(gated_client(OWNER)).json()
    assert body["actionable"] + body["blocked"] == body["planned"]
    assert body["actionable"] == 2 and body["blocked"] == 1     # b.docx has no Drive id


def test_a_delete_plan_states_the_trash_and_its_window(gated_client, queued):
    queued.bulk_create_disposition_audit([
        ("aud-del", f"scan:{SCAN}:a.docx", "retention", "delete", "pending_approval",
         "much older", OWNER, 3)])
    with queued._db.cursor() as cur:
        queued._db.execute(cur, "UPDATE disposition_policy SET action='delete' WHERE policy_id=%s",
                           ("retention",))
    body = _plan(gated_client(OWNER), audit_ids=["aud-del"], action="delete",
                 reason="records schedule 7 expired").json()
    step = body["plan"][0]
    assert "Google Drive trash" in step["will"]
    # The same claim api/disposition.py makes and no stronger — nothing reads a retention policy
    # back from Drive.
    assert "about 30 days" in step["recoverable"]


# ── the plan is validated exactly like the approval it previews ──────────────

def test_a_mixed_batch_is_refused_by_the_plan_too(gated_client, queued):
    queued.bulk_create_disposition_audit([
        ("audX", f"scan:{SCAN}:a.docx", "retention", "delete", "pending_approval",
         "much older", OWNER, 3)])
    r = _plan(gated_client(OWNER), audit_ids=["aud-a", "audX"])
    assert r.status_code == 409
    assert "nothing was planned" in r.json()["detail"]


def test_a_superseded_policy_version_is_refused_by_the_plan_too(gated_client, queued):
    with queued._db.cursor() as cur:
        queued._db.execute(cur, "UPDATE disposition_policy SET version=4 WHERE policy_id=%s",
                           ("retention",))
    r = _plan(gated_client(OWNER))
    assert r.status_code == 409
    assert "now version 4" in r.json()["detail"]


def test_a_delete_plan_still_needs_a_reason(gated_client, queued):
    """The plan applies the same rule, so a reviewer cannot preview their way around it."""
    r = _plan(gated_client(OWNER), audit_ids=["aud-a"], action="delete")
    assert r.status_code == 400 and "reason" in r.json()["detail"]


def test_an_empty_batch_is_refused(gated_client, queued):
    assert _plan(gated_client(OWNER), audit_ids=[]).status_code == 400


def test_a_non_owner_cannot_even_preview(gated_client, queued):
    """A preview of what would happen to somebody's estate is still a read of it."""
    assert _plan(gated_client(OTHER)).status_code in (401, 403)


def test_another_owners_row_resolves_to_nothing(gated_client, queued, isolated_store):
    isolated_store.bulk_create_disposition_audit([
        ("audTheirs", "scan:other:x.docx", "retention", "archive", "pending_approval",
         "theirs", OTHER, 3)])
    rows = {p["audit_id"]: p for p in
            _plan(gated_client(OWNER), audit_ids=["audTheirs"]).json()["plan"]}
    assert rows["audTheirs"]["blocked"] == "not found for this owner"


def test_an_already_decided_row_is_reported_not_replanned(gated_client, queued):
    queued.set_disposition_audit_result("aud-a", "approved", "done earlier")
    rows = {p["audit_id"]: p for p in _plan(gated_client(OWNER)).json()["plan"]}
    assert rows["aud-a"]["blocked"] == "already approved"


# ── plan_action itself, with no client at all ───────────────────────────────

def test_plan_action_takes_no_drive_client_and_makes_no_call():
    """Pure by construction: it accepts no svc, so it cannot reach the estate even by mistake."""
    import inspect

    import disposition
    assert "svc" not in inspect.signature(disposition.plan_action).parameters


def test_plan_action_describes_each_action_without_acting():
    import disposition
    doc = {"doc_id": "drive:f1", "source": "drive"}
    assert "trash" in disposition.plan_action(doc, "delete", {})["will"]
    assert "rename" in disposition.plan_action(doc, "rename", {})["will"]
    assert disposition.plan_action(doc, "leave", {})["blocked"] is None
    assert disposition.plan_action(doc, "tag", {"tags": []})["blocked"]
    assert disposition.plan_action(doc, "nonsense", {})["blocked"]


def test_plan_action_names_the_configured_destination_when_there_is_one():
    import disposition
    doc = {"doc_id": "drive:f1", "source": "drive"}
    assert "folder xyz" in disposition.plan_action(doc, "archive", {"target_folder_id": "xyz"})["target"]
    # And says the default one would be CREATED, rather than implying it exists.
    assert "created if it does not exist" in disposition.plan_action(doc, "archive", {})["target"]
