"""POST /disposition/preview — previewing a lifecycle rule BEFORE it is saved.

WHY THE ROUTE EXISTS. The only preview that existed was POST
/disposition/policies/{policy_id}/preview, which needs a saved policy id. So the rule editor could
only show "this matches 40 files" AFTER creating the rule — which is the wrong way round: the
count is the thing the decision is made ON. A person writing "everything under /Finance/2019 not
modified in five years" needs to know it selects 40 and not 40,000 before they commit.

WHAT IS UNDER TEST, in order of how much it would cost to get wrong:

  1. It creates NOTHING. A preview that leaves a policy row behind is a rule somebody can later
     enable by accident, and the whole safety posture here is that rules are created disabled and
     armed deliberately. Asserted against the policy table, the audit table and the tag table.
  2. It agrees with the saved preview. Two evaluators would let the count a person approved a rule
     on differ from the count that rule produces.
  3. It is admin-gated, with the same refusal shape as its neighbours.
  4. It validates like create — a predicate the backend would reject at save time must be rejected
     here, or the editor shows a count for a rule that cannot exist.
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


def _docs(st):
    """Three documents under two folders, with distinct ages — enough for a predicate to select a
    real subset rather than everything or nothing."""
    for doc_id, path, created in (
        ("drive:1", "Finance/2019/ledger.docx", "2019-01-01T00:00:00+00:00"),
        ("drive:2", "Finance/2019/notes.docx", "2019-06-01T00:00:00+00:00"),
        ("drive:3", "Clinical/current.docx", "2026-01-01T00:00:00+00:00"),
    ):
        st.upsert_document(doc_id, source="drive", path=path, content_hash=None, owner="demo",
                           created_at=created, last_seen="2026-08-20T00:00:00+00:00",
                           triage_score=10, triage_rationale="seeded", owner_email="demo")


FINANCE = [{"field": "parent_folder", "op": "prefix", "value": "Finance/2019"}]


# ── 1. It creates nothing ────────────────────────────────────────────────────────────────────

def test_previewing_a_draft_creates_no_policy(client):
    """The load-bearing property. A preview that persisted a rule would leave something that can
    be enabled later — and this rule was never approved by anybody."""
    c, st = client
    _docs(st)
    before = st.list_disposition_policies()
    r = c.post("/disposition/preview", json={"match": FINANCE, "action": "archive"})
    assert r.status_code == 200
    assert st.list_disposition_policies() == before == []


def test_previewing_a_draft_writes_no_audit_row_and_no_tag(client):
    """Read-only means read-only: no disposition_audit row, no file_tags, nothing to undo."""
    c, st = client
    _docs(st)
    c.post("/disposition/preview",
           json={"match": FINANCE, "action": "tag", "action_config": {"tags": ["stale"]}})
    assert st.list_disposition_audit() == []
    assert st.list_file_tags("drive:1", "Finance/2019/ledger.docx") == []


def test_a_delete_draft_touches_nothing_at_all(client):
    """The most dangerous action, previewed. It still only counts — no Drive client is even reached
    (this test would need one to trash anything), and nothing is recorded against the documents."""
    c, st = client
    _docs(st)
    body = c.post("/disposition/preview", json={"match": FINANCE, "action": "delete"}).json()
    assert body["would_match"] == 2
    assert st.list_disposition_audit() == []
    assert st.list_disposition_policies() == []
    # Every document is still there, unchanged.
    assert len(st.list_all_documents()) == 3


# ── 2. It agrees with the saved preview ──────────────────────────────────────────────────────

def test_the_draft_count_is_the_count_the_saved_rule_produces(client):
    """One evaluator, checked by running both. If these ever diverge, a person approves a rule on
    one number and gets another — which is the only way this feature can actively mislead."""
    c, st = client
    _docs(st)
    draft = c.post("/disposition/preview", json={"match": FINANCE, "action": "archive"}).json()

    st.create_disposition_policy("p1", name="stale-finance", match=json.dumps(FINANCE),
                                 action="archive", action_config="{}", requires_approval=True,
                                 enabled=False, owner_email="demo")
    saved = c.post("/disposition/policies/p1/preview").json()

    assert draft["would_match"] == saved["would_match"] == 2
    assert draft["documents"] == saved["documents"]
    assert draft["action"] == saved["action"] == "archive"


def test_the_response_carries_the_saved_previews_shape_with_a_null_id(client):
    """Same keys, so one client code path reads both. `policy_id` is null because this rule has no
    id — not because one went missing, and not omitted, which a caller would have to special-case."""
    c, st = client
    _docs(st)
    body = c.post("/disposition/preview", json={"match": FINANCE, "action": "archive"}).json()
    assert set(body) == {"policy_id", "action", "would_match", "total", "documents",
                         "effective", "superseded", "exempted", "unable_to_evaluate"}
    assert body["policy_id"] is None
    assert len(body["documents"]) == body["would_match"]
    assert body["total"] == 3   # all seeded documents, regardless of how many the rule matched


def test_it_selects_a_real_subset_not_everything(client):
    """A preview that matched everything regardless of the predicate would still pass the shape
    assertions above while being useless. Pin the actual selection."""
    c, st = client
    _docs(st)
    body = c.post("/disposition/preview", json={"match": FINANCE, "action": "archive"}).json()
    assert sorted(d["doc_id"] for d in body["documents"]) == ["drive:1", "drive:2"]

    none = c.post("/disposition/preview", json={
        "match": [{"field": "parent_folder", "op": "prefix", "value": "Nowhere/"}],
        "action": "archive"}).json()
    assert none["would_match"] == 0
    assert none["documents"] == []


def test_an_empty_match_selects_everything_and_says_so(client):
    """A rule with no conditions matches the whole estate. That must come back as the real number,
    not be defended against — it is exactly the mistake the preview exists to show somebody."""
    c, st = client
    _docs(st)
    body = c.post("/disposition/preview", json={"match": [], "action": "archive"}).json()
    assert body["would_match"] == 3


# ── 3. The admin gate ────────────────────────────────────────────────────────────────────────

def test_a_non_admin_is_refused_with_the_neighbours_refusal_shape(monkeypatch, isolated_store):
    """Same gate, same status, same body as create/execute. The predicate here is caller-supplied,
    so an ungated route would let any allow-listed user dump the documents table through an
    arbitrary filter."""
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com", raising=False)
    c = TestClient(app)
    _docs(isolated_store)

    refused = c.post("/disposition/preview", json={"match": FINANCE, "action": "archive"})
    created = c.post("/disposition/policies",
                     json={"name": "x", "match": FINANCE, "action": "archive"})
    assert refused.status_code == created.status_code == 403
    assert refused.json() == created.json() == {"detail": "admin access required"}


# ── 4. It validates like create ──────────────────────────────────────────────────────────────

def test_an_unknown_action_is_refused(client):
    c, _ = client
    r = c.post("/disposition/preview", json={"match": [], "action": "incinerate"})
    assert r.status_code == 422
    assert "action must be one of" in r.json()["detail"]


def test_a_predicate_create_would_reject_is_rejected_here_too(client):
    """Otherwise the editor shows a confident count for a rule that cannot be saved."""
    c, _ = client
    for bad in ([{"field": "cheese", "op": "eq", "value": 1}],
                [{"field": "path", "op": "sql", "value": 1}],
                [{"nofield": True}]):
        r = c.post("/disposition/preview", json={"match": bad, "action": "archive"})
        assert r.status_code == 422, bad


def test_a_tag_draft_with_no_tags_is_refused(client):
    """validate_action_config's rule, applied at preview: a tag policy with nothing to attach is a
    no-op that would otherwise report a match count for work it will never do."""
    c, _ = client
    r = c.post("/disposition/preview",
               json={"match": [], "action": "tag", "action_config": {"tags": []}})
    assert r.status_code == 422
    assert "tag" in r.json()["detail"]
