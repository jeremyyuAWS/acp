"""PRD Phase 3, §7.5 — the two things a rule test bench owes a person about to arm a rule.

WHY IT MATTERS THAT THE PREVIEW NAMES NON-MATCHES. It already returned every matching document,
every count, and an aggregate of which fields were missing. What it never returned was a single
file it REJECTED, and that is the half a rule gets debugged from: a rule selecting far fewer files
than expected is diagnosed by seeing what fell out and on which condition, not by re-reading the
count it produced. The data was already in hand — disposition.evaluate() runs for every document
in the loop and its failing condition was being discarded.

WHY THE APPROVAL CLAUSE HAS TEETH. §7.5 says a destructive rule "cannot disable approval without
an administrator capability and an explicit confirmation". `requires_approval` already defaulted
to True, which is the first half and the easy half. Nothing enforced the second, so one boolean in
a JSON body was the entire distance between "queued for a human" and a rule that moves or trashes
documents unattended — and routes/disposition.py's auto-apply branch is the one path in this
system that touches a file with no human in the loop.

The create-then-weaken bypass is guarded too, and is the one worth reading for: a rule created
correctly, with approval, could have it PATCHed away afterwards in a single field. That is both
the easier path to take and the harder one to notice later.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"


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


@pytest.fixture()
def estate(isolated_store):
    """One document that matches and three that do not, so the non-match sample is never empty.

    owner_email is the TENANT column and `owner` is the business-owner fact the rule matches on —
    a distinction that cost this fixture a rewrite: setting only `owner` left every document
    invisible to list_all_documents and the preview reported total=0, which the first draft of
    these tests read as "nothing to say" rather than "the fixture is wrong"."""
    st = isolated_store
    st.upsert_document("drive:fin", source="drive", path="/estate/finance.docx",
                       owner="finance@x.com", owner_email=OWNER, content_hash=None,
                       created_at=None, last_seen=None, triage_score=None, triage_rationale=None)
    for i in range(3):
        st.upsert_document(f"drive:hr{i}", source="drive", path=f"/estate/hr{i}.docx",
                           owner="hr@x.com", owner_email=OWNER, content_hash=None,
                           created_at=None, last_seen=None, triage_score=None,
                           triage_rationale=None)
    return st


MATCH = [{"field": "owner", "op": "eq", "value": "finance@x.com"}]


def _preview(client, match=None):
    r = client.post("/disposition/preview",
                    json={"match": match or MATCH, "action": "archive", "action_config": {}})
    assert r.status_code == 200, r.text
    return r.json()


# ── representative non-matches ───────────────────────────────────────────────

def test_the_preview_names_documents_it_rejected(gated_client, estate):
    """Unconditional. The first draft guarded this behind `if would_match < total`, so deleting
    the feature left it green — a test that examines nothing reports the same pass as one that
    examined everything."""
    body = _preview(gated_client)
    assert body["total"] == 4 and body["would_match"] == 1, body
    assert body["near_misses"], "three documents were rejected and none was named"
    named = {m["path"] for m in body["near_misses"]}
    assert named <= {"/estate/hr0.docx", "/estate/hr1.docx", "/estate/hr2.docx"}
    assert "/estate/finance.docx" not in named, "a MATCHING document was reported as a near miss"


def test_a_near_miss_says_which_condition_failed(gated_client, estate):
    body = _preview(gated_client)
    assert body["near_misses"], "nothing to assert on"
    for miss in body["near_misses"]:
        # The field and a human reason, not just a path — "it didn't match" is what the reader
        # already knew before they asked.
        assert miss["field"] == "owner"
        assert miss["observed_value"] == "hr@x.com"
        assert miss["reason"], "no reason given for the rejection"
        assert miss["unevaluable"] is False, (
            "a document with the field present was reported as unevaluable")


def test_a_missing_field_is_reported_as_unevaluable_not_as_a_mismatch(gated_client, estate):
    """"We could not tell" and "it does not match" send a reader to different places: one is a
    rule to fix, the other is metadata to go and collect."""
    body = _preview(gated_client, match=[{"field": "department", "op": "eq", "value": "Legal"}])
    assert body["near_misses"]
    assert all(m["unevaluable"] for m in body["near_misses"])
    assert body["unable_to_evaluate"] > 0


def test_the_sample_is_bounded(gated_client, isolated_store, estate):
    """Asserted against a LITERAL, not against _NEAR_MISS_SAMPLE. Asserting against the constant
    made this pass when the constant was mutated to 100000 — the test moved with the thing it was
    supposed to be checking."""
    for i in range(40):
        isolated_store.upsert_document(
            f"drive:extra{i}", source="drive", path=f"/estate/extra{i}.docx",
            owner="hr@x.com", owner_email=OWNER, content_hash=None, created_at=None,
            last_seen=None, triage_score=None, triage_rationale=None)
    body = _preview(gated_client)
    rejected = body["total"] - body["would_match"]
    assert rejected >= 40, "the fixture did not produce enough non-matches to bound"
    assert len(body["near_misses"]) <= 10, (
        f"{len(body['near_misses'])} near misses returned — this fires on every keystroke in the "
        f"rule editor and must stay a sample, not a second result set")
    assert len(body["near_misses"]) < rejected, "the 'sample' is the whole set"


def test_the_matched_side_is_unchanged(gated_client, estate):
    """Additive: everything the preview reported before is still reported."""
    body = gated_client.post("/disposition/preview",
                             json={"match": MATCH, "action": "archive",
                                   "action_config": {}}).json()
    for key in ("would_match", "total", "documents", "effective", "superseded",
                "exempted", "exempted_documents", "unable_to_evaluate",
                "unable_to_evaluate_fields"):
        assert key in body, f"the preview stopped reporting {key}"


# ── §7.5's approval clause ───────────────────────────────────────────────────

def _create(client, **over):
    body = {"name": "R", "match": MATCH, "action": "delete", "action_config": {},
            "requires_approval": False}
    body.update(over)
    return client.post("/disposition/policies", json=body)


@pytest.mark.parametrize("action", ["delete", "archive", "move", "rename"])
def test_a_source_mutating_rule_cannot_skip_approval_unasked(gated_client, action):
    r = _create(gated_client, action=action,
                action_config={"template": "{name}"} if action == "rename" else {})
    assert r.status_code == 422, f"{action} armed itself unattended: {r.status_code}"
    assert "no human review" in r.json()["detail"]
    assert "confirm_unattended" in r.json()["detail"], "the refusal does not say how to proceed"


@pytest.mark.parametrize("action", ["leave", "tag"])
def test_a_metadata_only_rule_is_not_gated(gated_client, action):
    """Gating these would train people to send the flag by reflex, which is how a confirmation
    stops meaning anything. Neither changes a file."""
    r = _create(gated_client, action=action,
                action_config={"tags": ["x"]} if action == "tag" else {})
    assert r.status_code == 200, r.text


def test_the_confirmation_lets_it_through(gated_client):
    r = _create(gated_client, confirm_unattended=True)
    assert r.status_code == 200, r.text
    pid = r.json()["policy_id"]
    assert gated_client.get("/disposition/policies").json()[0]["policy_id"] == pid


def test_requiring_approval_needs_no_confirmation(gated_client):
    assert _create(gated_client, requires_approval=True).status_code == 200


def test_approval_cannot_be_patched_away_afterwards(gated_client):
    """THE bypass. A rule created correctly, then weakened in a one-field PATCH — the easier path
    to take and the harder to notice later."""
    pid = _create(gated_client, requires_approval=True).json()["policy_id"]
    r = gated_client.put(f"/disposition/policies/{pid}", json={"requires_approval": False})
    assert r.status_code == 422, "approval was edited away without a confirmation"
    assert "no human review" in r.json()["detail"]

    ok = gated_client.put(f"/disposition/policies/{pid}",
                          json={"requires_approval": False, "confirm_unattended": True})
    assert ok.status_code == 200, ok.text


def test_the_action_set_is_owned_by_the_module_that_defines_actions(gated_client):
    """SOURCE_MUTATING lives beside ACTIONS, not in the route. A second copy in the API layer
    would keep the old approval requirements when a new mutating action was added."""
    import disposition
    assert disposition.SOURCE_MUTATING <= disposition.ACTIONS
    assert "delete" in disposition.SOURCE_MUTATING
    assert "tag" not in disposition.SOURCE_MUTATING and "leave" not in disposition.SOURCE_MUTATING
