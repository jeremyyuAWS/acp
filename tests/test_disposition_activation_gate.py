"""A rule that changes files cannot be turned on until somebody has seen what it selects.

PRD §7.5: "A rule cannot activate until preview completes successfully."

WHAT THAT HAS TO MEAN TO BE WORTH ANYTHING. Not that a preview *could* run — the server can always
run one, and a gate the server satisfies on the caller's behalf is a gate nobody passes through.
It has to mean a PERSON saw the result. So the caller states the count they were shown, and the
server re-derives it at the moment of activation and refuses if the rule no longer selects that
many.

THE WINDOW THIS CLOSES. Somebody previews a rule at 12 files, goes to lunch, a Discover run lands
4,000 more documents, and the toggle they come back to arms the rule against an estate they never
looked at. The rule did not change and neither did the UI; the ESTATE did. Re-deriving the count
at activation is the only point where that is visible.

Two exemptions, both deliberate and both tested:

  · Disabling is never gated. It is the safety valve, and a valve you have to argue with is not
    one.
  · tag and leave change no file. Gating them would train people through the confirmation by
    reflex, which is how a confirmation stops meaning anything — the same reasoning that exempts
    them from confirm_unattended.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
MATCH = [{"field": "owner", "op": "eq", "value": "finance@x.com"}]


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
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {OWNER}"})
    return client


def _doc(st, doc_id, owner_field):
    st.upsert_document(doc_id, source="drive", path=f"/estate/{doc_id}.docx",
                       owner=owner_field, owner_email=OWNER, content_hash=None,
                       created_at=None, last_seen=None, triage_score=None,
                       triage_rationale=None)


@pytest.fixture()
def estate(isolated_store):
    """Two documents the rule selects, one it does not."""
    _doc(isolated_store, "fin1", "finance@x.com")
    _doc(isolated_store, "fin2", "finance@x.com")
    _doc(isolated_store, "hr1", "hr@x.com")
    return isolated_store


def _rule(client, action="archive", **over):
    body = {"name": "R", "match": MATCH, "action": action, "action_config": {}}
    body.update(over)
    r = client.post("/disposition/policies", json=body)
    assert r.status_code == 200, r.text
    return r.json()["policy_id"]


def _enable(client, pid, count=None, enabled=True):
    q = f"enabled={'true' if enabled else 'false'}"
    if count is not None:
        q += f"&previewed_match_count={count}"
    return client.put(f"/disposition/policies/{pid}/enabled?{q}")


def test_a_file_changing_rule_cannot_be_armed_without_a_preview(gated_client, estate):
    pid = _rule(gated_client)
    r = _enable(gated_client, pid)
    assert r.status_code == 422
    assert "cannot be turned on until someone has seen what it selects" in r.json()["detail"]


def test_the_refusal_names_the_current_count_so_a_client_can_learn_it(gated_client, estate):
    """Two-step and self-describing: a caller finds out what to confirm by asking, rather than
    needing to have called the preview endpoint first and remembered the number."""
    pid = _rule(gated_client)
    detail = _enable(gated_client, pid).json()["detail"]
    assert "matches 2 document(s)" in detail
    assert "previewed_match_count=2" in detail


def test_confirming_the_right_count_arms_it(gated_client, estate):
    pid = _rule(gated_client)
    assert _enable(gated_client, pid, count=2).status_code == 200
    assert gated_client.get("/disposition/policies").json()[0]["enabled"]


def test_a_stale_count_is_refused_and_says_both_numbers(gated_client, estate, isolated_store):
    """THE window. The rule is unchanged and so is the UI — the ESTATE moved under it."""
    pid = _rule(gated_client)
    _doc(isolated_store, "fin3", "finance@x.com")      # a Discover run lands another match
    r = _enable(gated_client, pid, count=2)            # confirming what was seen before lunch
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "selected 2" in detail and "selects 3 now" in detail
    assert not gated_client.get("/disposition/policies").json()[0]["enabled"]


def test_the_rule_is_not_armed_when_the_gate_refuses(gated_client, estate):
    """A refusal that half-applied would be worse than no gate at all."""
    pid = _rule(gated_client)
    _enable(gated_client, pid)
    _enable(gated_client, pid, count=99)
    assert not gated_client.get("/disposition/policies").json()[0]["enabled"]


@pytest.mark.parametrize("action", ["archive", "delete", "move", "rename"])
def test_every_file_changing_action_is_gated(gated_client, estate, action):
    cfg = {"template": "{name}"} if action == "rename" else {}
    pid = _rule(gated_client, action=action, action_config=cfg)
    assert _enable(gated_client, pid).status_code == 422, f"{action} armed without a preview"


@pytest.mark.parametrize("action", ["tag", "leave"])
def test_a_metadata_only_rule_is_not_gated(gated_client, estate, action):
    """They change no file. Gating them would train people through the confirmation by reflex."""
    cfg = {"tags": ["x"]} if action == "tag" else {}
    pid = _rule(gated_client, action=action, action_config=cfg)
    assert _enable(gated_client, pid).status_code == 200, r"a metadata-only rule was gated"


def test_disabling_is_never_gated(gated_client, estate):
    """The safety valve. A valve you have to argue with is not one."""
    pid = _rule(gated_client)
    _enable(gated_client, pid, count=2)
    r = _enable(gated_client, pid, enabled=False)
    assert r.status_code == 200
    assert not gated_client.get("/disposition/policies").json()[0]["enabled"]


def test_disabling_needs_no_count_even_when_the_estate_has_moved(gated_client, estate,
                                                                 isolated_store):
    pid = _rule(gated_client)
    _enable(gated_client, pid, count=2)
    _doc(isolated_store, "fin9", "finance@x.com")
    assert _enable(gated_client, pid, enabled=False).status_code == 200


def test_a_rule_whose_preview_cannot_run_is_not_activated(gated_client, estate, isolated_store,
                                                          monkeypatch):
    """"until preview completes SUCCESSFULLY". A rule whose conditions cannot be evaluated is
    precisely the one nobody should be arming on trust."""
    pid = _rule(gated_client)
    import routes.disposition as rd

    def _boom(*a, **k):
        raise RuntimeError("condition evaluator blew up")

    monkeypatch.setattr(rd, "_preview", _boom)
    r = _enable(gated_client, pid, count=2)
    assert r.status_code == 422
    assert "did not complete" in r.json()["detail"]
    assert not gated_client.get("/disposition/policies").json()[0]["enabled"]


def test_a_zero_match_rule_can_still_be_armed_deliberately(gated_client):
    """Zero is a real answer, not a missing one — arming a rule that currently selects nothing is
    a legitimate thing to do, and the gate must not confuse "no matches" with "no preview"."""
    pid = _rule(gated_client)
    assert _enable(gated_client, pid, count=0).status_code == 200


def test_another_owners_rule_is_still_a_404_not_a_preview(gated_client, estate, isolated_store):
    """The gate runs a preview against the estate; it must not become a way to learn how many
    documents somebody else's rule would select."""
    isolated_store.create_disposition_policy(
        "theirs", name="Theirs", match=json.dumps(MATCH), action="archive", action_config="{}",
        requires_approval=True, enabled=False, owner_email="someone-else@example.com")
    r = _enable(gated_client, "theirs")
    assert r.status_code == 404
    assert "document" not in r.json()["detail"].lower(), "the 404 leaked a count"
