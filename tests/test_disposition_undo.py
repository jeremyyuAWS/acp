"""Putting a file back where ACP moved it (PRD §8's undo).

WHY THIS COULD NOT EXIST BEFORE. disposition.execute_action already read everything an undo
needs and threw it away: a move read the file's parents and passed them straight to
removeParents, a rename read the prior name only to build the new one. Both were gone the
instant they were used, so nothing in the system could put a file back — the connector always
supported it, ACP simply never wrote down where the file came from. execute_action now returns
that before-state and the routes persist it.

THE RULE THIS FILE IS REALLY ABOUT: an undo that cannot verify the prior state must refuse. A
file restored to a folder nobody recorded is indistinguishable, afterwards, from a file moved
somewhere new — so "no before-state" is a refusal, never a best guess at My Drive. The same goes
for a FAILED action, which may or may not have moved the file at all.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"


class _Files:
    """The two Drive calls execute_action/undo_action use, recorded rather than performed."""

    def __init__(self, state):
        self.state = state

    def get(self, fileId=None, fields=None):
        return _Exec(dict(self.state))

    def update(self, fileId=None, body=None, addParents=None, removeParents=None, fields=None):
        if body and "trashed" in body:
            self.state["trashed"] = body["trashed"]
        if body and "name" in body:
            self.state["name"] = body["name"]
        if addParents:
            keep = [p for p in self.state.get("parents", [])
                    if p not in (removeParents or "").split(",")]
            self.state["parents"] = keep + addParents.split(",")
        return _Exec({"id": fileId})


class _Exec:
    def __init__(self, payload):
        self._p = payload

    def execute(self):
        return self._p


class _Svc:
    def __init__(self, state):
        self._files = _Files(state)

    def files(self):
        return self._files


def _doc():
    return {"doc_id": "drive:f1", "source": "drive", "path": "/estate/q.docx"}


# ── the before-state execute_action now returns ──────────────────────────────

def test_a_move_records_where_the_file_came_from():
    import disposition
    state = {"parents": ["origin-folder"], "name": "q.docx", "trashed": False}
    # target_folder_id supplied so the action does not go looking for the archive folder —
    # _ensure_folder issues a files().list() this fake deliberately does not implement, and the
    # subject here is the before-state, not folder discovery.
    result, detail, before = disposition.execute_action(
        _doc(), "archive", {"target_folder_id": "archive-folder"}, _Svc(state))
    assert result == "applied", detail
    assert before["parents"] == ["origin-folder"], "the origin was discarded again"
    assert before["action"] == "archive"


def test_a_rename_records_the_previous_name():
    import disposition
    state = {"parents": ["p"], "name": "q.docx", "trashed": False}
    result, detail, before = disposition.execute_action(_doc(), "rename", {}, _Svc(state))
    assert result == "applied"
    assert before == {"action": "rename", "name": "q.docx"}


def test_a_delete_records_that_it_was_not_in_the_trash():
    import disposition
    state = {"parents": ["p"], "name": "q.docx", "trashed": False}
    _, _, before = disposition.execute_action(_doc(), "delete", {}, _Svc(state))
    assert before == {"action": "delete", "trashed": False}


def test_a_failure_records_no_before_state():
    """It may or may not have moved. A "before" that might be untrue is worse than none, because
    an undo would act on the guess."""
    import disposition

    class _Boom:
        def files(self):
            raise RuntimeError("drive is down")

    result, _, before = disposition.execute_action(
        _doc(), "archive", {"target_folder_id": "archive-folder"}, _Boom())
    assert result == "failed"
    assert before is None


def test_metadata_only_actions_record_nothing():
    import disposition
    for action in ("leave", "tag"):
        cfg = {"tags": ["x"]} if action == "tag" else {}
        _, _, before = disposition.execute_action(_doc(), action, cfg, None)
        assert before is None, f"{action} moved no file but recorded a before-state"


# ── undo_action itself ───────────────────────────────────────────────────────

def test_undo_moves_the_file_back_to_its_recorded_parent():
    import disposition
    state = {"parents": ["archive-folder"], "name": "q.docx", "trashed": False}
    svc = _Svc(state)
    result, detail = disposition.undo_action(
        _doc(), {"action": "archive", "parents": ["origin-folder"]}, svc)
    assert result == "applied"
    assert state["parents"] == ["origin-folder"], state["parents"]


def test_undo_restores_from_trash():
    import disposition
    state = {"parents": ["p"], "name": "q.docx", "trashed": True}
    result, detail = disposition.undo_action(_doc(), {"action": "delete", "trashed": False},
                                             _Svc(state))
    assert result == "applied"
    assert state["trashed"] is False


def test_undo_restores_the_previous_name():
    import disposition
    state = {"parents": ["p"], "name": "q [ARCHIVED].docx", "trashed": False}
    result, _ = disposition.undo_action(_doc(), {"action": "rename", "name": "q.docx"},
                                        _Svc(state))
    assert result == "applied"
    assert state["name"] == "q.docx"


def test_undo_refuses_without_a_before_state():
    import disposition
    result, detail = disposition.undo_action(_doc(), None, _Svc({}))
    assert result == "failed"
    assert "no before-state" in detail


def test_undo_refuses_when_the_previous_folder_was_not_recorded():
    """THE dangerous case. A file that genuinely had no parent and one whose parents were never
    recorded are indistinguishable here, and dropping it into My Drive would be a move to
    somewhere it has never been — dressed up as a restoration."""
    import disposition
    state = {"parents": ["archive-folder"]}
    result, detail = disposition.undo_action(_doc(), {"action": "archive", "parents": []},
                                             _Svc(state))
    assert result == "failed"
    assert "previous folder was not recorded" in detail
    assert state["parents"] == ["archive-folder"], "the file was moved despite the refusal"


def test_undo_refuses_a_non_drive_document():
    import disposition
    result, detail = disposition.undo_action(
        {"doc_id": "sp:1", "source": "sharepoint"}, {"action": "delete"}, _Svc({}))
    assert result == "failed"
    assert "unsupported source" in detail


# ── the route ────────────────────────────────────────────────────────────────

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
def applied(isolated_store):
    st = isolated_store
    st.create_disposition_policy("retention", name="R", match="[]", action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    st.upsert_document("drive:f1", source="drive", path="/estate/q.docx", owner=OWNER,
                       content_hash=None, created_at=None, last_seen=None,
                       triage_score=None, triage_rationale=None)
    st.create_disposition_audit("aud1", doc_id="drive:f1", policy_id="retention",
                                action="archive", result="applied", detail="moved",
                                owner_email=OWNER)
    st.set_disposition_before_state("aud1", {"action": "archive", "parents": ["origin-folder"]})
    return st


def test_the_route_undoes_an_applied_action(gated_client, applied, monkeypatch):
    import routes.disposition as rd
    state = {"parents": ["archive-folder"]}
    monkeypatch.setattr(rd, "_drive_svc", lambda request: _Svc(state))
    r = gated_client(OWNER).post("/disposition/approvals/aud1/undo")
    assert r.status_code == 200, r.text
    assert state["parents"] == ["origin-folder"]


def test_the_undo_is_appended_rather_than_erasing_the_original(gated_client, applied, monkeypatch):
    """The audit is append-only by design. "archived, then restored" is the true history; a row
    that quietly reverted to pending would claim the archive never happened."""
    import routes.disposition as rd
    monkeypatch.setattr(rd, "_drive_svc", lambda request: _Svc({"parents": ["archive-folder"]}))
    body = gated_client(OWNER).post("/disposition/approvals/aud1/undo").json()
    assert applied.get_disposition_audit("aud1", owner=OWNER)["result"] == "applied"
    undo_row = applied.get_disposition_audit(body["audit_id"], owner=OWNER)
    assert undo_row["action"] == "undo_archive"
    assert undo_row["result"] == "applied"


def test_a_row_with_no_before_state_is_refused(gated_client, applied, monkeypatch):
    """Applied before this column existed. Nothing recorded where it came from, so there is no
    honest restoration available."""
    import routes.disposition as rd
    applied.create_disposition_audit("old", doc_id="drive:f1", policy_id="retention",
                                     action="archive", result="applied", detail="moved",
                                     owner_email=OWNER)
    monkeypatch.setattr(rd, "_drive_svc", lambda request: _Svc({"parents": ["a"]}))
    r = gated_client(OWNER).post("/disposition/approvals/old/undo")
    assert r.status_code == 409
    assert "no before-state" in r.json()["detail"]


def test_a_failed_action_cannot_be_undone(gated_client, applied, monkeypatch):
    import routes.disposition as rd
    applied.create_disposition_audit("bad", doc_id="drive:f1", policy_id="retention",
                                     action="archive", result="failed", detail="boom",
                                     owner_email=OWNER)
    monkeypatch.setattr(rd, "_drive_svc", lambda request: _Svc({"parents": ["a"]}))
    r = gated_client(OWNER).post("/disposition/approvals/bad/undo")
    assert r.status_code == 409
    assert "only an applied action" in r.json()["detail"]


def test_a_non_owner_cannot_undo(gated_client, applied, monkeypatch):
    import routes.disposition as rd
    state = {"parents": ["archive-folder"]}
    monkeypatch.setattr(rd, "_drive_svc", lambda request: _Svc(state))
    r = gated_client(OTHER).post("/disposition/approvals/aud1/undo")
    assert r.status_code in (401, 403)
    assert state["parents"] == ["archive-folder"], "a non-owner moved a file"


def test_another_owners_row_is_not_undoable(gated_client, applied):
    applied.create_disposition_audit("theirs", doc_id="drive:f9", policy_id="retention",
                                     action="archive", result="applied", detail="moved",
                                     owner_email=OTHER)
    r = gated_client(OWNER).post("/disposition/approvals/theirs/undo")
    assert r.status_code == 404


def test_the_before_state_is_never_overwritten(applied):
    """A second write would mean the stored 'before' no longer describes the state the first
    action moved the file out of — and an undo against that is a move to somewhere the file has
    never been."""
    applied.set_disposition_before_state("aud1", {"action": "archive", "parents": ["WRONG"]})
    assert applied.get_disposition_before_state("aud1", OWNER)["parents"] == ["origin-folder"]


def test_an_unreadable_before_state_refuses_rather_than_guessing(applied):
    with applied._db.cursor() as cur:
        applied._db.execute(cur, "UPDATE disposition_audit SET before_state=%s WHERE id=%s",
                            ("{not json", "aud1"))
    assert applied.get_disposition_before_state("aud1", OWNER) is None
