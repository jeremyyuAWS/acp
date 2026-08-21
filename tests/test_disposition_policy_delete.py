"""DELETE /disposition/policies/{policy_id} — removing a saved lifecycle rule outright.

THE QUESTION THIS ROUTE HAS TO ANSWER, same one update_policy already answers for edits: can a
rule that has produced recorded outcomes disappear? disposition_audit rows and
scan_inventory.lifecycle_rule_id references name a rule by its policy_id and nothing else — no
other column explains what the rule was. Delete the row and those references point at nothing an
auditor can look up: "matched archive rule 'p-a1b2c3'" with no rule left to show for it is worse
than a rule that sits around disabled.

THE DECISION, mirroring update_policy's: a rule with ANY recorded history — 'rejected' and
'failed' outcomes included, same as _policy_has_history's own reasoning — is refused with 409.
Its only path out is disable, same as an edit's. A rule that never ran has nothing pointing at
it, so removing it loses nothing on record.

Uses the same plain (unauthenticated -> owner="demo") client fixture as
test_disposition_policy_update.py, since delete and update share the same admin/owner posture.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

MATCH = [{"field": "modified_age_days", "op": "gt", "value": 1825}]


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


def _rule(st, policy_id="p1", *, enabled=False, owner_email="demo"):
    st.create_disposition_policy(policy_id, name="stale finance", match=json.dumps(MATCH),
                                 action="archive", action_config="{}",
                                 requires_approval=True, enabled=enabled, owner_email=owner_email)
    return policy_id


def _ran(st, policy_id="p1", owner_email="demo", result="pending_approval"):
    st.create_disposition_audit("a1", doc_id="scan:s1:Finance/ledger.docx", policy_id=policy_id,
                                action="archive", result=result,
                                detail="matched archive rule 'stale finance'",
                                owner_email=owner_email)


def test_a_rule_that_never_ran_can_be_deleted(client):
    c, st = client
    _rule(st)
    r = c.delete("/disposition/policies/p1")
    assert r.status_code == 200
    assert r.json() == {"deleted": "p1"}
    assert st.get_disposition_policy("p1") is None


def test_a_rule_with_history_is_refused_not_deleted(client):
    c, st = client
    _rule(st, enabled=True)
    _ran(st)
    r = c.delete("/disposition/policies/p1")
    assert r.status_code == 409
    assert "already run" in r.json()["detail"]
    # Refused, not partially applied — the row and its history both survive.
    assert st.get_disposition_policy("p1") is not None


def test_a_rejected_outcome_still_counts_as_history(client):
    """Same reasoning as _policy_has_history's own docstring: a rejected row still names the
    rule, so it still blocks deletion — this is not a "successful outcomes only" guard."""
    c, st = client
    _rule(st)
    _ran(st, result="rejected")
    assert c.delete("/disposition/policies/p1").status_code == 409


def test_missing_policy_is_404(client):
    c, _ = client
    assert c.delete("/disposition/policies/nope").status_code == 404


def test_deleting_leaves_other_policies_untouched(client):
    c, st = client
    _rule(st, policy_id="p1")
    _rule(st, policy_id="p2")
    c.delete("/disposition/policies/p1")
    assert st.get_disposition_policy("p1") is None
    assert st.get_disposition_policy("p2") is not None
