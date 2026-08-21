"""GET /disposition/policies/conflicts — files matched by 2+ enabled rules, and which wins.

Lifecycle Rules build-plan item #6, conflict half. Before this there was no way to find out
which files a rule ambiguity affects except by running Discover and reading the result after the
fact. This computes the SAME decision (disposition.resolve_candidate — the exact function
_evaluate_discover_lifecycle_rules calls) on demand against the current rules and estate, so a
conflict is visible before the next Discover run, not only after.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"


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


def _doc(st, doc_id, path):
    st.upsert_document(doc_id, source="drive", path=path, content_hash=None, owner=OWNER,
                       created_at="2019-01-01T00:00:00+00:00", last_seen="2026-08-20T00:00:00+00:00",
                       triage_score=0, triage_rationale="", owner_email=OWNER)


def _policy(st, policy_id, name, *, action, match, enabled=True, action_config=None):
    st.create_disposition_policy(policy_id, name=name, match=json.dumps(match), action=action,
                                 action_config=json.dumps(action_config or {}),
                                 requires_approval=True, enabled=enabled, owner_email=OWNER)


def test_no_conflicts_when_only_one_enabled_rule_matches(client):
    c, st = client
    _doc(st, "d1", "Finance/2019/ledger.docx")
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    assert c.get("/disposition/policies/conflicts").json() == {"conflicts": []}


def test_a_tag_plus_archive_overlap_is_not_a_conflict(client):
    """Every matching tag rule applies independently of the candidate decision — the two aren't
    competing for the same outcome, so this must not be reported as a conflict."""
    c, st = client
    _doc(st, "d1", "Finance/2019/ledger.docx")
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    _policy(st, "p2", "tag finance", action="tag",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}],
           action_config={"tags": ["reviewed"]})
    assert c.get("/disposition/policies/conflicts").json() == {"conflicts": []}


def test_two_archive_rules_report_the_first_priority_as_winner(client):
    c, st = client
    _doc(st, "d1", "Finance/2019/ledger.docx")
    _policy(st, "p1", "archive by folder", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    _policy(st, "p2", "archive by age", action="archive",
           match=[{"field": "age_days", "op": "gt", "value": 1}])
    body = c.get("/disposition/policies/conflicts").json()
    assert len(body["conflicts"]) == 1
    conflict = body["conflicts"][0]
    assert conflict["doc_id"] == "d1"
    assert {r["policy_id"] for r in conflict["matched_rules"]} == {"p1", "p2"}
    assert conflict["winner"]["policy_id"] == "p1"   # p1 created first -> priority 1
    assert conflict["outcome"] == "Archive Candidate"


def test_archive_vs_delete_reports_the_safe_default_and_names_why(client):
    c, st = client
    _doc(st, "d1", "Finance/2019/ledger.docx")
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    _policy(st, "p2", "delete finance", action="delete",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])   # no override config
    conflict = c.get("/disposition/policies/conflicts").json()["conflicts"][0]
    assert conflict["outcome"] == "Archive Candidate"
    assert conflict["winner"]["policy_id"] == "p1"
    assert "not permitted" in conflict["reason"] or "not authorized" in conflict["reason"]


def test_disabled_rules_are_never_part_of_a_conflict(client):
    c, st = client
    _doc(st, "d1", "Finance/2019/ledger.docx")
    _policy(st, "p1", "archive finance", action="archive",
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    _policy(st, "p2", "delete finance", action="delete", enabled=False,
           match=[{"field": "path", "op": "prefix", "value": "Finance/"}])
    assert c.get("/disposition/policies/conflicts").json() == {"conflicts": []}


def test_conflicts_are_scoped_to_the_caller_tenant(client):
    c, st = client
    _doc(st, "d1", "Finance/2019/ledger.docx")
    st.upsert_document("d2", source="drive", path="Finance/2019/ledger.docx", content_hash=None,
                       owner="other", created_at="2019-01-01T00:00:00+00:00",
                       last_seen="2026-08-20T00:00:00+00:00", triage_score=0, triage_rationale="",
                       owner_email="someone.else@example.com")
    st.create_disposition_policy("t1", name="a", match=json.dumps([{"field": "path", "op": "prefix", "value": "Finance/"}]),
                                 action="archive", action_config="{}", requires_approval=True,
                                 enabled=True, owner_email="someone.else@example.com")
    st.create_disposition_policy("t2", name="b", match=json.dumps([{"field": "path", "op": "prefix", "value": "Finance/"}]),
                                 action="delete", action_config="{}", requires_approval=True,
                                 enabled=True, owner_email="someone.else@example.com")
    # The other tenant has a real conflict on d2 — none of it should be visible to OWNER.
    assert c.get("/disposition/policies/conflicts").json() == {"conflicts": []}
