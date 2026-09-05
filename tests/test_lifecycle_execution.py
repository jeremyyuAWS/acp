"""A reviewer's approval of a Discover-lifecycle candidate actually moves the file (PRD §8).

WHAT WAS MISSING. Every precondition for executing an archival decision shipped — the preview
with its breakdown and near-misses (#1216), the dry-run plan (#1192), the per-row cap (#1213),
the unattended guard and the activation gate (#1218), before-state capture (#1190), undo. The
execution was not there. `POST /disposition/approvals/{id}/approve?execute=true` on a lifecycle
candidate answered:

    {"executed": false, "why_not_executed": "lifecycle candidates have no governance-layer
     document"}

So a reviewer could preview 812 matches, confirm the count, approve a capped batch under a named
policy version, and receive a receipt for something that had not happened. Everything read like
it worked. The gap was an identifier: the evaluator stamps `scan:{scan_id}:{file}` and the
governance layer keys on `drive:{id}`, and the drive_file_id that bridges them had been on the
inventory row since Discover wrote it.

DRIVE ONLY, and that is a property rather than a shortfall to apologise for: ACP holds read-only
scopes on SharePoint/OneDrive (sharepointScopes.CAN_WRITE_BACK is false), so a route that claimed
to move those files would be describing a capability the deployment does not have. A candidate
with no drive_file_id stays record-only — pinned in
test_lifecycle_approval_is_not_a_missing_document.py, which owns that half.

THE FOUR THINGS THESE TESTS ARE ACTUALLY FOR, none of which is the happy path:

  1. The exemption is re-read immediately before the mutation. Queued at 10:00, put on legal hold
     at 10:02, approved at 10:05 — the hold must win, and must not also consume the decision.
  2. The estate is stamped only when the action APPLIED. A candidate whose archive failed is
     still Active, and the inventory is the view a reviewer checks to see whether anything moved.
  3. The undo restores both halves. Putting the file back in Drive while Discover still reads
     "Archived" and Assess still excludes it is an undo of the visible half only.
  4. The resolution is owner-scoped. Resolving a file id out of somebody else's scan and acting
     on it is the worst thing this feature could do, so it is asserted rather than reasoned about.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"
SCAN = "scan-exec-1"
ARCHIVE = "archive-folder"


# ── a Drive that records rather than performs ────────────────────────────────

class _Exec:
    def __init__(self, payload):
        self._p = payload

    def execute(self):
        return self._p


class _Files:
    """The calls execute_action and undo_action make, recorded rather than performed."""

    def __init__(self, state):
        self.state = state
        self.touched: list[str] = []          # every fileId an update was issued against

    def get(self, fileId=None, fields=None):
        return _Exec(dict(self.state))

    def update(self, fileId=None, body=None, addParents=None, removeParents=None, fields=None):
        self.touched.append(fileId)
        if body and "trashed" in body:
            self.state["trashed"] = body["trashed"]
        if body and "name" in body:
            self.state["name"] = body["name"]
        if addParents:
            keep = [p for p in self.state.get("parents", [])
                    if p not in (removeParents or "").split(",")]
            self.state["parents"] = keep + addParents.split(",")
        return _Exec({"id": fileId})


class _Svc:
    def __init__(self, state):
        self._files = _Files(state)

    def files(self):
        return self._files


class _Boom(_Svc):
    """A Drive that refuses the write. execute_action converts it to a 'failed' result rather
    than raising — one bad file must not abort a policy run — which is exactly the state test 2
    above needs: an action that did not apply."""

    def files(self):
        class _F(_Files):
            def update(self, **kw):
                raise RuntimeError("drive said no")
        return _F(self._files.state)


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
def drive(monkeypatch):
    """The Drive the route will be given, returned so a test can read what happened to it."""
    import routes.disposition as rd
    svc = _Svc({"parents": ["origin-folder"], "name": "a.docx", "trashed": False})
    monkeypatch.setattr(rd, "_drive_svc", lambda request: svc)
    return svc


def _seed(st, *, action="archive", cfg=None, files=None, scan=SCAN, owner=OWNER):
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) "
                            "VALUES(%s,%s,%s,%s)", (scan, owner, "discovered", "drive"))
    st.add_inventory(scan, files or [
        {"file": "a.docx", "path": "/estate/a.docx", "owner": owner, "drive_file_id": "fid-a"},
    ])
    return st


@pytest.fixture()
def queued(isolated_store):
    """One archive candidate that CAN be executed: it has a drive_file_id."""
    st = _seed(isolated_store)
    st.create_disposition_policy("retention", name="Retention", match="[]", action="archive",
                                 action_config=json.dumps({"target_folder_id": ARCHIVE}),
                                 requires_approval=True, enabled=True, owner_email=OWNER)
    st.bulk_create_disposition_audit([
        ("aud-a", f"scan:{SCAN}:a.docx", "retention", "archive", "pending_approval",
         "older than the cutoff", OWNER, 1),
    ])
    return st


def _approve(client, audit_id="aud-a"):
    return client.post(f"/disposition/approvals/{audit_id}/approve?execute=true")


# ── the execution itself ─────────────────────────────────────────────────────

def test_the_file_actually_moves(gated_client, queued, drive):
    """THE defect. The reviewer's approval reaches Drive instead of stopping at a receipt."""
    r = _approve(gated_client(OWNER))
    assert r.status_code == 200, r.text
    assert drive.files().state["parents"] == [ARCHIVE], "the file never moved"
    row = queued.get_disposition_audit("aud-a", owner=OWNER)
    assert row["result"] == "applied", f"recorded as {row['result']!r}: {row['detail']!r}"


def test_the_response_no_longer_claims_nothing_was_executed(gated_client, queued, drive):
    body = _approve(gated_client(OWNER)).json()
    assert body.get("why_not_executed") is None
    assert body["result"] == "applied"


def test_the_origin_is_recorded_so_it_can_be_undone(gated_client, queued, drive):
    """An execution with no before-state is a one-way door, whatever the undo route promises."""
    _approve(gated_client(OWNER))
    before = queued.get_disposition_before_state("aud-a", OWNER)
    assert before["parents"] == ["origin-folder"]
    assert before["action"] == "archive"


def test_the_estate_stops_calling_an_archived_file_active(gated_client, queued, drive):
    """Discover's inventory is where the next reviewer looks to see whether anything moved. Left
    at 'Active' it contradicts the audit, and Assess keeps offering a file that is in the archive."""
    _approve(gated_client(OWNER))
    assert queued.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Archived"


def test_a_delete_is_stamped_deleted_not_archived(gated_client, isolated_store, drive):
    st = _seed(isolated_store)
    st.create_disposition_policy("purge", name="Purge", match="[]", action="delete",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    st.bulk_create_disposition_audit([
        ("aud-d", f"scan:{SCAN}:a.docx", "purge", "delete", "pending_approval", "expired",
         OWNER, 1)])
    assert _approve(gated_client(OWNER), "aud-d").status_code == 200
    assert drive.files().state["trashed"] is True
    assert st.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Deleted"


def test_a_rename_leaves_the_status_alone(gated_client, isolated_store, drive):
    """A renamed file has not been archived. The status vocabulary has no word for 'renamed', and
    borrowing 'Archived' would exclude a live document from Assess on the strength of a new name."""
    st = _seed(isolated_store)
    st.create_disposition_policy("mark", name="Mark", match="[]", action="rename",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    st.bulk_create_disposition_audit([
        ("aud-r", f"scan:{SCAN}:a.docx", "mark", "rename", "pending_approval", "old", OWNER, 1)])
    assert _approve(gated_client(OWNER), "aud-r").status_code == 200
    assert st.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Active"


def test_a_failed_action_does_not_stamp_the_estate(gated_client, queued, monkeypatch):
    """The one that hides a failure. Stamping on approval rather than on result would leave the
    inventory saying 'Archived' about a file still sitting in its original folder."""
    import routes.disposition as rd
    monkeypatch.setattr(rd, "_drive_svc",
                        lambda request: _Boom({"parents": ["origin-folder"], "name": "a.docx"}))
    _approve(gated_client(OWNER))
    assert queued.get_disposition_audit("aud-a", owner=OWNER)["result"] == "failed"
    assert queued.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Active"


def test_a_failure_records_no_before_state(gated_client, queued, monkeypatch):
    """It may or may not have moved. A 'before' that might be untrue is worse than none."""
    import routes.disposition as rd
    monkeypatch.setattr(rd, "_drive_svc",
                        lambda request: _Boom({"parents": ["origin-folder"], "name": "a.docx"}))
    _approve(gated_client(OWNER))
    assert queued.get_disposition_before_state("aud-a", OWNER) is None


# ── the hold that arrives while the reviewer is reading ──────────────────────

def test_an_exemption_added_after_queueing_stops_the_mutation(gated_client, queued, drive):
    """PRD §11, fail-closed, re-read immediately before the action. The batch route always did
    this; the per-row route did not need to while it could not act."""
    queued.set_lifecycle_status(SCAN, "a.docx", "Exempted", reason="legal hold")
    r = _approve(gated_client(OWNER))
    assert r.status_code == 409, r.text
    assert "Exempted" in r.json()["detail"]
    assert drive.files().state["parents"] == ["origin-folder"], "a file on hold was moved"


def test_a_hold_does_not_also_consume_the_decision(gated_client, queued, drive):
    """The row stays PENDING. Refusing the action and destroying the approval are different
    outcomes, and a queue that makes a reviewer decide twice stops being trusted."""
    queued.set_lifecycle_status(SCAN, "a.docx", "Exempted", reason="legal hold")
    _approve(gated_client(OWNER))
    assert queued.get_disposition_audit("aud-a", owner=OWNER)["result"] == "pending_approval"


def test_a_reviewer_override_stops_the_mutation(gated_client, queued, drive):
    """A human already said 'keep this'. Executing the rule's recommendation would silently
    overturn a reasoned individual decision."""
    queued.set_lifecycle_status(SCAN, "a.docx", "Archive Candidate")
    with queued._db.cursor() as cur:
        queued._db.execute(cur, "UPDATE scan_inventory SET lifecycle_override_reason=%s "
                                "WHERE scan_id=%s AND file=%s", ("still in use", SCAN, "a.docx"))
    r = _approve(gated_client(OWNER))
    assert r.status_code == 409
    assert "overridden" in r.json()["detail"]
    assert drive.files().state["parents"] == ["origin-folder"]


# ── whose estate it is ──────────────────────────────────────────────────────

def test_a_file_id_cannot_be_resolved_out_of_another_owners_scan(gated_client, isolated_store,
                                                                 drive):
    """The worst thing this feature could do. The audit row is the caller's; the SCAN is not, so
    drive_targets_for_files (which joins scan_runs.owner_email) must not hand back the id."""
    st = _seed(isolated_store, scan="scan-theirs", owner=OTHER)
    st.create_disposition_policy("retention", name="Retention", match="[]", action="archive",
                                 action_config=json.dumps({"target_folder_id": ARCHIVE}),
                                 requires_approval=True, enabled=True, owner_email=OWNER)
    st.bulk_create_disposition_audit([
        ("aud-x", "scan:scan-theirs:a.docx", "retention", "archive", "pending_approval",
         "old", OWNER, 1)])
    body = _approve(gated_client(OWNER), "aud-x").json()
    assert body["executed"] is False, "a file in another owner's scan was actioned"
    assert drive.files().touched == []


def test_a_non_owner_cannot_execute(gated_client, queued, drive):
    r = _approve(gated_client(OTHER))
    assert r.status_code in (401, 403)
    assert drive.files().state["parents"] == ["origin-folder"]
    assert queued.get_disposition_audit("aud-a", owner=OWNER)["result"] == "pending_approval"


def test_record_only_still_touches_nothing(gated_client, queued, drive):
    """execute=false is the honest half and must stay exactly that, now that the other half
    exists to be confused with it."""
    r = gated_client(OWNER).post("/disposition/approvals/aud-a/approve?execute=false")
    assert r.status_code == 200
    assert drive.files().touched == []
    assert queued.get_disposition_audit("aud-a", owner=OWNER)["result"] == "approved"


# ── undo restores both halves ───────────────────────────────────────────────

def test_undo_puts_a_lifecycle_file_back(gated_client, queued, drive):
    """Before this, undo handed undo_action a `scan:` id labelled source='drive', which
    _drive_file_id rejects — so the rows most needing reversal refused with 'unsupported
    source', a message that is both wrong and impossible to act on."""
    _approve(gated_client(OWNER))
    r = gated_client(OWNER).post("/disposition/approvals/aud-a/undo")
    assert r.status_code == 200, r.text
    assert drive.files().state["parents"] == ["origin-folder"]


def test_undo_restores_the_lifecycle_status_too(gated_client, queued, drive):
    """Restoring the file in Drive while Discover still reads 'Archived' and Assess still
    excludes it is an undo of the visible half only."""
    _approve(gated_client(OWNER))
    assert queued.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Archived"
    gated_client(OWNER).post("/disposition/approvals/aud-a/undo")
    assert queued.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Active"


def test_undo_does_not_report_an_unsupported_source(gated_client, queued, drive):
    _approve(gated_client(OWNER))
    body = gated_client(OWNER).post("/disposition/approvals/aud-a/undo").json()
    assert "unsupported source" not in json.dumps(body)


# ── the plan and the execution are of the same thing ────────────────────────

def test_the_plan_previews_the_document_the_approval_acts_on(gated_client, queued, drive):
    """The drift this guards is invisible: a plan resolved by a second copy of the rules can show
    a document the execution does not act on, and nothing would say so. Asserted by identity —
    the file id the plan displayed is the file id Drive was called with."""
    plan = gated_client(OWNER).post("/disposition/approvals/plan", json={
        "audit_ids": ["aud-a"], "policy_id": "retention", "policy_version": 1,
        "action": "archive"}).json()
    assert plan["executed"] is False and plan["dry_run"] is True
    previewed = plan["plan"][0]["drive_file_id"]
    assert previewed == "fid-a"
    _approve(gated_client(OWNER))
    assert drive.files().touched == [previewed]


def test_planning_still_writes_nothing(gated_client, queued, drive):
    """A dry run that can mutate is not a dry run — and it now sits beside a path that does."""
    gated_client(OWNER).post("/disposition/approvals/plan", json={
        "audit_ids": ["aud-a"], "policy_id": "retention", "policy_version": 1,
        "action": "archive"})
    assert drive.files().touched == []
    assert queued.get_disposition_audit("aud-a", owner=OWNER)["result"] == "pending_approval"
    assert queued.get_lifecycle_status(SCAN, "a.docx")["lifecycle_status"] == "Active"


# ── the identifier helpers ──────────────────────────────────────────────────

def test_a_malformed_lifecycle_id_is_refused_rather_than_split(gated_client):
    """_is_lifecycle_doc_id tests the prefix, which a two-part id also has. Taking the pieces
    from one would raise ValueError inside a route that had already accepted the row."""
    from routes.disposition import _lifecycle_ref
    assert _lifecycle_ref("scan:s1:a.docx") == ("s1", "a.docx")
    assert _lifecycle_ref("scan:s1:folder/a.docx") == ("s1", "folder/a.docx")
    assert _lifecycle_ref("scan:s1") is None
    assert _lifecycle_ref("drive:abc") is None
    assert _lifecycle_ref(None) is None


def test_only_actions_the_status_can_state_are_stamped():
    """A bare `move` goes wherever the policy configured, which is not necessarily an archive."""
    from routes.disposition import _TERMINAL_STATUS
    assert _TERMINAL_STATUS == {"archive": "Archived", "delete": "Deleted"}
