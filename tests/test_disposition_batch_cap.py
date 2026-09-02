"""One approval may not cover an unbounded number of files.

THE COST, measured rather than estimated. The approve loop is 3.0 queries per row — _exempt_now's
lifecycle re-read, the audit result write, and _trace_decision's document lookup — and it writes
as it goes, with no transaction around it. 200 rows cost 603 queries locally. At 6,000 that is
~18,000 round trips in a single request; against Postgres over a network it is tens of seconds,
and a gateway timeout leaves rows already approved with NO response saying which.

That is the failure worth stopping. PRD §8 requires a partial batch never be reported as
successful — and a timeout does not report a partial batch, it reports nothing, which is the same
failure with the evidence removed. The reviewer then cannot tell whether to retry, and retrying a
half-applied batch is how an approval queue loses a reviewer's trust for good.

The second reason is plainer: a confirmation covering thousands of files is not consent. The
queue pages at 25/50/100, so a reviewer can only see a hundred rows at once.

WHERE IT LIVES MATTERS. On _validated_batch, which the dry-run plan and the approval share, so a
plan can never preview a batch the approval would refuse — the drift that sharing that function
exists to prevent.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"
SCAN = "scan-cap"


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
    """Enough rows to sit either side of the cap."""
    from routes.disposition import MAX_BATCH_ROWS
    st = isolated_store
    n = MAX_BATCH_ROWS + 5
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,%s,%s)",
                       (SCAN, OWNER, "discovered", "drive"))
    st.add_inventory(SCAN, [{"file": f"f{i}.docx", "path": f"/estate/f{i}.docx", "owner": OWNER}
                            for i in range(n)])
    st.create_disposition_policy("retention", name="Retention", match="[]", action="archive",
                                 action_config="{}", requires_approval=True, enabled=True,
                                 owner_email=OWNER)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE disposition_policy SET version=3 WHERE policy_id=%s",
                       ("retention",))
    st.bulk_create_disposition_audit([
        (f"a{i}", f"scan:{SCAN}:f{i}.docx", "retention", "archive", "pending_approval",
         "older than the cutoff", OWNER, 3) for i in range(n)])
    for i in range(n):
        st.set_lifecycle_status(SCAN, f"f{i}.docx", "Archive Candidate",
                                rule_id="retention", reason="older than the cutoff")
    return st


def _ids(n):
    return [f"a{i}" for i in range(n)]


def _post(client, path, ids, **over):
    body = {"audit_ids": ids, "policy_id": "retention", "policy_version": 3, "action": "archive"}
    body.update(over)
    return client.post(path, json=body)


def test_a_batch_over_the_cap_is_refused(gated_client, queued):
    from routes.disposition import MAX_BATCH_ROWS
    r = _post(gated_client(OWNER), "/disposition/approvals", _ids(MAX_BATCH_ROWS + 1))
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert str(MAX_BATCH_ROWS) in detail
    assert str(MAX_BATCH_ROWS + 1) in detail, "the refusal does not say how many were submitted"


def test_nothing_is_approved_when_the_batch_is_refused(gated_client, queued):
    """The refusal happens in validation, before the loop — so an over-sized batch does not
    approve its first 500 and then stop, which would be the partial nobody was told about."""
    from routes.disposition import MAX_BATCH_ROWS
    _post(gated_client(OWNER), "/disposition/approvals", _ids(MAX_BATCH_ROWS + 5))
    still_pending = [i for i in range(MAX_BATCH_ROWS + 5)
                     if queued.get_disposition_audit(f"a{i}", owner=OWNER)["result"]
                     == "pending_approval"]
    assert len(still_pending) == MAX_BATCH_ROWS + 5, "a refused batch approved something anyway"


def test_the_refusal_says_what_to_do_about_it(gated_client, queued):
    from routes.disposition import MAX_BATCH_ROWS
    detail = _post(gated_client(OWNER), "/disposition/approvals",
                   _ids(MAX_BATCH_ROWS + 1)).json()["detail"]
    assert "smaller batches" in detail
    # The reason, not just the rule: a cap with no stated cost reads as an arbitrary limit and
    # gets raised by the next person who finds it inconvenient.
    assert "time out" in detail


def test_a_batch_exactly_at_the_cap_is_accepted(gated_client, queued):
    """Off-by-one in the safe direction is still a bug: it makes the documented number a lie."""
    from routes.disposition import MAX_BATCH_ROWS
    r = _post(gated_client(OWNER), "/disposition/approvals", _ids(MAX_BATCH_ROWS))
    assert r.status_code == 200, r.text
    assert len(r.json()["approved"]) == MAX_BATCH_ROWS


def test_the_cap_counts_rows_after_de_duplication(gated_client, queued):
    """Submitted ids are de-duped before counting, so a client that repeats an id is not refused
    for a batch it did not send."""
    from routes.disposition import MAX_BATCH_ROWS
    ids = _ids(MAX_BATCH_ROWS) + _ids(MAX_BATCH_ROWS)      # every id twice
    r = _post(gated_client(OWNER), "/disposition/approvals", ids)
    assert r.status_code == 200, r.text
    assert r.json()["submitted"] == MAX_BATCH_ROWS


def test_the_dry_run_refuses_at_the_same_point(gated_client, queued):
    """THE coupling. A plan that previewed 2,000 rows the approval would then refuse is exactly
    the drift sharing _validated_batch exists to prevent."""
    from routes.disposition import MAX_BATCH_ROWS
    over = _post(gated_client(OWNER), "/disposition/approvals/plan", _ids(MAX_BATCH_ROWS + 1))
    assert over.status_code == 400
    at = _post(gated_client(OWNER), "/disposition/approvals/plan", _ids(MAX_BATCH_ROWS))
    assert at.status_code == 200, at.text
    assert at.json()["planned"] == MAX_BATCH_ROWS


def test_an_ordinary_batch_is_unaffected(gated_client, queued):
    r = _post(gated_client(OWNER), "/disposition/approvals", _ids(3))
    assert r.status_code == 200
    assert sorted(r.json()["approved"]) == ["a0", "a1", "a2"]
    assert r.json()["reconciled"] is True


def test_the_cap_is_a_stated_number_not_a_magic_one(gated_client):
    """Imported by these tests rather than hardcoded, so raising it cannot leave the tests
    asserting the old value while the route enforces a new one."""
    from routes.disposition import MAX_BATCH_ROWS
    assert isinstance(MAX_BATCH_ROWS, int) and MAX_BATCH_ROWS > 0
