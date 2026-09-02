"""PUT /disposition/policies/{policy_id} — editing a saved lifecycle rule.

THE QUESTION THIS ROUTE HAD TO ANSWER FIRST. A rule that has run has produced records that name
it: disposition_audit rows, and scan_inventory rows whose `lifecycle_rule_id` points at it with a
`lifecycle_reason` quoting it by name. Those records carry the rule's ID and NOTHING ELSE — no
column anywhere records which DEFINITION of the rule produced them.

So an in-place edit of a rule that has run silently rewrites the past. A file flagged "Archive
Candidate — matched archive rule 'stale finance'" under "not modified in five years" would, after
an edit, read to every future reader as having matched "not modified in 90 days". Nothing errors,
nothing moves, only the meaning changes — retroactively, for evidence a reviewer relies on.

THE DECISION, PINNED HERE: edits apply going forward; existing records keep the definition that
produced them. A rule that has produced any recorded outcome may no longer change its DEFINITION
(match / action / action_config) — 409. Name and requires_approval stay editable, because neither
alters which files were selected or what was recommended for them.

The other half of what these cases guard is the thing an update route makes newly possible and
must never do: ARM A RULE. `enabled` is not in the payload at all, and the tests check that a
disabled rule is still disabled after every kind of edit.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


OLD = [{"field": "modified_age_days", "op": "gt", "value": 1825}]
NEW = [{"field": "modified_age_days", "op": "gt", "value": 90}]


def _rule(st, policy_id="p1", *, match=None, action="archive", enabled=False,
          action_config="{}", requires_approval=True, owner_email="demo"):
    st.create_disposition_policy(policy_id, name="stale finance",
                                 match=json.dumps(OLD if match is None else match),
                                 action=action, action_config=action_config,
                                 requires_approval=requires_approval, enabled=enabled,
                                 owner_email=owner_email)
    return policy_id


def _ran(st, policy_id="p1", owner_email="demo"):
    """Give the rule a history: one flagged file and the audit row that names it — exactly the
    pair handlers._evaluate_discover_lifecycle_rules writes at discovery."""
    st.create_disposition_audit("a1", doc_id="scan:s1:Finance/ledger.docx", policy_id=policy_id,
                                action="archive", result="pending_approval",
                                detail="matched archive rule 'stale finance'",
                                owner_email=owner_email)


# ── A rule that has produced nothing is fully editable ───────────────────────────────────────

def test_a_rule_that_never_ran_can_be_edited(client):
    """The case the rule editor is in nearly every time: rules are created disabled, and are
    tweaked before they are ever armed. There is only one definition, so nothing can be rewritten."""
    c, st = client
    _rule(st)
    r = c.put("/disposition/policies/p1",
              json={"name": "stale finance (90d)", "match": NEW})
    assert r.status_code == 200
    saved = st.get_disposition_policy("p1")
    assert saved["name"] == "stale finance (90d)"
    assert json.loads(saved["match"]) == NEW


def test_an_omitted_field_is_left_alone(client):
    """A rename must not blank the predicate — the editor sends what changed."""
    c, st = client
    _rule(st, action_config=json.dumps({"target_folder_id": "folder-1"}))
    c.put("/disposition/policies/p1", json={"name": "renamed"})
    saved = st.get_disposition_policy("p1")
    assert saved["name"] == "renamed"
    assert json.loads(saved["match"]) == OLD
    assert json.loads(saved["action_config"]) == {"target_folder_id": "folder-1"}
    assert saved["action"] == "archive"
    assert bool(saved["requires_approval"]) is True


def test_the_action_can_be_changed_before_the_rule_has_run(client):
    c, st = client
    _rule(st)
    r = c.put("/disposition/policies/p1", json={"action": "delete"})
    assert r.status_code == 200
    assert st.get_disposition_policy("p1")["action"] == "delete"


def test_missing_policy_is_404(client):
    c, _ = client
    assert c.put("/disposition/policies/nope", json={"name": "x"}).status_code == 404


# ── AN EDIT CAN NEVER ARM A RULE ─────────────────────────────────────────────────────────────

def test_an_edit_never_enables_a_disabled_rule(client):
    """`enabled` is not in the payload, and a caller that sends it anyway is ignored. An edit that
    could also arm the rule turns "fix the folder path" into "start running this now"."""
    c, st = client
    _rule(st, enabled=False)
    c.put("/disposition/policies/p1",
          json={"name": "n", "match": NEW, "enabled": True, "action": "delete"})
    assert not st.get_disposition_policy("p1")["enabled"]


def test_an_edit_never_disables_an_enabled_rule_either(client):
    """The same omission, read the other way: enablement is owned entirely by its own route, so an
    edit cannot silently stop a rule an operator believes is running."""
    c, st = client
    _rule(st, enabled=True)
    _ran(st)                                   # enabled rules generally have history
    c.put("/disposition/policies/p1", json={"name": "renamed"})
    assert st.get_disposition_policy("p1")["enabled"]


# ── A RULE THAT HAS RUN KEEPS THE DEFINITION THAT PRODUCED ITS RECORDS ───────────────────────

def test_a_rule_that_has_run_cannot_change_its_match(client):
    c, st = client
    _rule(st)
    _ran(st)
    r = c.put("/disposition/policies/p1", json={"match": NEW})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "already run" in detail and "match" in detail
    # And the stored rule is untouched — a refusal that half-applied would be worse than either.
    assert json.loads(st.get_disposition_policy("p1")["match"]) == OLD


def test_a_rule_that_has_run_cannot_change_its_action(client):
    """The one that would most change what history means: every audit row says 'archive'."""
    c, st = client
    _rule(st)
    _ran(st)
    r = c.put("/disposition/policies/p1", json={"action": "delete"})
    assert r.status_code == 409
    assert st.get_disposition_policy("p1")["action"] == "archive"


def test_a_rule_that_has_run_cannot_change_its_action_config(client):
    c, st = client
    _rule(st, action="tag", action_config=json.dumps({"tags": ["stale"]}))
    _ran(st)
    r = c.put("/disposition/policies/p1", json={"action_config": {"tags": ["obsolete"]}})
    assert r.status_code == 409
    assert json.loads(st.get_disposition_policy("p1")["action_config"]) == {"tags": ["stale"]}


def test_the_refusal_says_what_to_do_instead(client):
    """A 409 that only says no leaves somebody stuck with a rule they cannot fix. It has to name
    the way forward — a new rule — and say the old rule's history survives."""
    c, st = client
    _rule(st)
    _ran(st)
    detail = c.put("/disposition/policies/p1", json={"match": NEW}).json()["detail"]
    assert "Create a new rule" in detail
    assert "disable this one" in detail
    assert "name and approval requirement are still editable" in detail


def test_a_rule_that_has_run_can_still_be_renamed(client):
    """A name does not change which files were selected or what was recommended for them, so
    freezing it would be a restriction that buys no safety."""
    c, st = client
    _rule(st)
    _ran(st)
    # confirm_unattended because this PATCH also turns approval OFF on an `archive` rule, and
    # PRD §7.5 now requires that to be asked for explicitly. Incidental to what this test is
    # about — the subject is that a rule which has RUN can still be renamed — but sending it
    # keeps the test honest rather than having the guard relaxed to let it through.
    r = c.put("/disposition/policies/p1",
              json={"name": "stale finance (superseded)", "requires_approval": False,
                    "confirm_unattended": True})
    assert r.status_code == 200
    saved = st.get_disposition_policy("p1")
    assert saved["name"] == "stale finance (superseded)"
    assert not saved["requires_approval"]
    assert json.loads(saved["match"]) == OLD          # definition untouched


def test_resending_the_same_definition_is_not_a_change(client):
    """The editor round-trips the whole rule on save. Sending back what is already stored must not
    be refused as an edit — only a DIFFERENT definition is one."""
    c, st = client
    _rule(st)
    _ran(st)
    r = c.put("/disposition/policies/p1",
              json={"name": "renamed", "match": OLD, "action": "archive", "action_config": {}})
    assert r.status_code == 200
    assert st.get_disposition_policy("p1")["name"] == "renamed"


@pytest.mark.parametrize("result", ["applied", "rejected", "failed", "approved"])
def test_any_recorded_outcome_counts_as_history(client, result):
    """Including rejected and failed. doc_has_disposition treats those as non-live so a re-run may
    propose the document again — a different question. Here the question is whether a stored record
    NAMES this rule, and 'rejected: matched delete rule X' names it just as loudly."""
    c, st = client
    _rule(st)
    st.create_disposition_audit("a9", doc_id="drive:9", policy_id="p1", action="archive",
                                result=result, detail="whatever happened", owner_email="demo")
    assert c.put("/disposition/policies/p1", json={"match": NEW}).status_code == 409


def test_another_rules_history_does_not_freeze_this_one(client):
    """The guard is per-policy. A shared check would freeze the whole estate's rules the moment any
    one of them ran."""
    c, st = client
    _rule(st, "p1")
    _rule(st, "p2")
    st.create_disposition_audit("a1", doc_id="drive:1", policy_id="p2", action="archive",
                                result="applied", detail="p2 ran", owner_email="demo")
    assert c.put("/disposition/policies/p1", json={"match": NEW}).status_code == 200


# ── Validated exactly like create ────────────────────────────────────────────────────────────

def test_an_unknown_field_is_refused(client):
    c, st = client
    _rule(st)
    r = c.put("/disposition/policies/p1",
              json={"match": [{"field": "cheese", "op": "eq", "value": 1}]})
    assert r.status_code == 422
    assert json.loads(st.get_disposition_policy("p1")["match"]) == OLD


def test_an_unknown_action_is_refused(client):
    c, st = client
    _rule(st)
    assert c.put("/disposition/policies/p1", json={"action": "incinerate"}).status_code == 422


def test_the_RESULTING_policy_is_validated_not_the_patch(client):
    """Switching an archive rule to 'tag' without supplying tags produces a tag policy with nothing
    to attach — a silent no-op that would otherwise only surface at execute time. Judged as the
    policy it produces, so it is caught here."""
    c, st = client
    _rule(st, action="archive", action_config="{}")
    r = c.put("/disposition/policies/p1", json={"action": "tag"})
    assert r.status_code == 422
    assert "tag" in r.json()["detail"]
    assert st.get_disposition_policy("p1")["action"] == "archive"


# ── The admin gate ───────────────────────────────────────────────────────────────────────────

def test_a_non_admin_is_refused_with_the_neighbours_refusal_shape(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com", raising=False)
    c = TestClient(app)
    _rule(isolated_store)

    refused = c.put("/disposition/policies/p1", json={"name": "x"})
    neighbour = c.put("/disposition/policies/p1/enabled?enabled=true")
    assert refused.status_code == neighbour.status_code == 403
    assert refused.json() == neighbour.json() == {"detail": "admin access required"}
    # And nothing changed under the refusal.
    assert isolated_store.get_disposition_policy("p1")["name"] == "stale finance"
