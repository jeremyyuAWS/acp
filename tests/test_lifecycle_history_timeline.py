"""One document's lifecycle timeline, across scans (PRD §7.4).

The right-hand review panel is specified to show "prior scans, recommendations, overrides,
approvals, and source actions". Each of those lives in a different table, and the value of
putting them on one line is that it crosses SCANS: "recommended in August, kept, recommended
again in September" is a different story from "recommended", and only the first one tells a
reviewer whether the rule is arguing with a person.

Two traps this pins, because both are invisible when they break:

  - The history is keyed on `file`, not on a lifecycle doc id. Those ids embed the scan
    (`scan:{scan_id}:{file}`), so keying on one returns a single scan's events and looks
    exactly like a complete history with nothing before it.
  - `{document_id:path}` is greedy, and FastAPI resolves routes in DECLARATION order. Declared
    after the detail route, /history is not a 404 — it is silently answered BY the detail route
    with document_id="foo.docx/history", which returns a 404 for a document of that name. The
    symptom looks like a missing document, not a misrouted request.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "someone-else@example.com"
FILE = "quarterly.docx"


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


def _scan(store, sid, owner=OWNER):
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) "
                               "VALUES(%s,%s,%s,%s)", (sid, owner, "discovered", "drive"))
    store.add_inventory(sid, [{"file": FILE, "path": f"/estate/{FILE}", "owner": owner}])


@pytest.fixture()
def two_scans(isolated_store):
    """August recommended it and a reviewer kept it; September recommended it again and it was
    approved. That is the shape the panel exists to make legible."""
    st = isolated_store
    _scan(st, "scan-aug")
    _scan(st, "scan-sep")

    st.bulk_create_lifecycle_evaluations([
        ("ev-aug", "scan-aug", FILE, "retention", 2, "matched", "{}", "archive", 10,
         "2026-08-01T09:00:00+00:00", OWNER),
        ("ev-sep", "scan-sep", FILE, "retention", 3, "matched", "{}", "archive", 10,
         "2026-09-01T09:00:00+00:00", OWNER),
    ])
    # override_lifecycle refuses on a file no rule flagged (correctly — there is nothing to
    # disagree with), so the candidate status has to exist before the reviewer disagrees with it.
    st.set_lifecycle_status("scan-aug", FILE, "Archive Candidate",
                            rule_id="retention", reason="older than the cutoff")
    assert st.override_lifecycle("scan-aug", FILE, reason="still cited by the 2019 audit",
                                 actor=OWNER) is not None
    st.bulk_create_disposition_audit([
        ("aud-sep", f"scan:scan-sep:{FILE}", "retention", "archive", "approved",
         "approved in batch under retention v3", OWNER, 3),
    ])
    st.log_decision(OWNER, "disposition.batch_approved", scan_id="scan-sep", file=FILE,
                    detail="1 approved")
    return st


def _events(client, sid=("scan-sep")):
    r = client.get(f"/scans/{sid}/lifecycle/files/{FILE}/history")
    assert r.status_code == 200, r.text
    return r.json()["events"]


def test_the_history_route_is_not_swallowed_by_the_detail_route(gated_client, two_scans):
    """THE routing trap. Declared after the detail route, this returns 404 "document not found"
    for a document literally named "quarterly.docx/history" — which reads as a data problem."""
    r = gated_client(OWNER).get(f"/scans/scan-sep/lifecycle/files/{FILE}/history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "events" in body, f"the detail route answered instead: {sorted(body)}"
    assert body["document_id"] == FILE


def test_the_timeline_crosses_scans(gated_client, two_scans):
    """Keyed on the file, so August is visible from September. Keyed on a lifecycle doc id it
    would not be, and the panel would look complete while showing one scan."""
    events = _events(gated_client(OWNER))
    scans = {e["scan_id"] for e in events}
    assert scans == {"scan-aug", "scan-sep"}, scans


def test_every_specified_kind_of_event_is_present(gated_client, two_scans):
    kinds = {e["kind"] for e in _events(gated_client(OWNER))}
    assert kinds == {"evaluated", "override", "approval", "decision"}, kinds


def test_it_reads_forwards(gated_client, two_scans):
    stamps = [e["ts"] for e in _events(gated_client(OWNER)) if e["ts"]]
    assert stamps == sorted(stamps), "a timeline that is not in order is not a timeline"
    assert stamps[0].startswith("2026-08-01")


def test_a_recommendation_carries_the_rule_version_it_was_made_under(gated_client, two_scans):
    versions = {(e["policy_id"], e["policy_version"]) for e in _events(gated_client(OWNER))
                if e["kind"] == "evaluated"}
    # The same rule argued twice, under two different versions. Collapsing them would make the
    # August recommendation look like it was made under today's rule.
    assert versions == {("retention", 2), ("retention", 3)}


def test_the_override_names_who_kept_it_and_why(gated_client, two_scans):
    override = next(e for e in _events(gated_client(OWNER)) if e["kind"] == "override")
    assert override["actor"] == OWNER
    assert "2019 audit" in override["detail"]
    assert override["scan_id"] == "scan-aug"


def test_the_approval_names_its_policy_version(gated_client, two_scans):
    approval = next(e for e in _events(gated_client(OWNER)) if e["kind"] == "approval")
    assert approval["policy_version"] == 3
    assert approval["result"] == "approved"
    assert approval["scan_id"] == "scan-sep"


def test_an_undated_event_is_kept_rather_than_dropped(gated_client, two_scans, isolated_store):
    """An event that happened is evidence even when nothing recorded when. Dropping it would
    quietly shorten the history; sorting it last keeps the readable part readable."""
    isolated_store.bulk_create_lifecycle_evaluations([
        ("ev-undated", "scan-aug", FILE, "legacy", 1, "matched", "{}", "archive", 10, None, OWNER),
    ])
    events = _events(gated_client(OWNER))
    assert any(e["policy_id"] == "legacy" for e in events)
    assert events[-1]["policy_id"] == "legacy", "the undated event displaced dated ones"


def test_another_owners_history_is_not_reachable(gated_client, two_scans, isolated_store):
    """Every source is owner-scoped independently — none of them infers ownership from another,
    which is the mistake a four-table merge invites."""
    _scan(isolated_store, "scan-theirs", owner=OTHER)
    isolated_store.bulk_create_lifecycle_evaluations([
        ("ev-theirs", "scan-theirs", FILE, "secret-rule", 1, "matched", "{}", "archive", 10,
         "2026-08-15T09:00:00+00:00", OTHER),
    ])
    isolated_store.bulk_create_disposition_audit([
        ("aud-theirs", f"scan:scan-theirs:{FILE}", "secret-rule", "archive", "approved",
         "theirs", OTHER, 1),
    ])
    events = _events(gated_client(OWNER))
    assert all(e["scan_id"] != "scan-theirs" for e in events)
    assert not any("secret-rule" == e["policy_id"] for e in events)


def test_a_foreign_scan_in_the_path_is_a_404(gated_client, two_scans, isolated_store):
    _scan(isolated_store, "scan-theirs", owner=OTHER)
    r = gated_client(OWNER).get(f"/scans/scan-theirs/lifecycle/files/{FILE}/history")
    assert r.status_code == 404


def test_a_document_with_no_history_is_an_empty_timeline_not_an_error(gated_client, two_scans):
    r = gated_client(OWNER).get("/scans/scan-sep/lifecycle/files/never-seen.docx/history")
    assert r.status_code == 200
    assert r.json()["events"] == []


def test_the_timeline_costs_a_fixed_number_of_queries(gated_client, two_scans, isolated_store):
    """Four sources, four queries, however long the history is. A per-event lookup here would
    scale with the document's whole past — see #1163 for the same shape next door."""
    isolated_store.bulk_create_lifecycle_evaluations([
        (f"ev-bulk{i}", "scan-aug", FILE, f"rule{i}", 1, "matched", "{}", "archive", 10,
         f"2026-08-{i + 2:02d}T09:00:00+00:00", OWNER) for i in range(30)])

    adapter = isolated_store._db
    original = adapter.execute
    seen = {"n": 0}

    def counting(cur, sql, params=()):
        seen["n"] += 1
        return original(cur, sql, params)

    adapter.execute = counting
    try:
        events = _events(gated_client(OWNER))
    finally:
        adapter.execute = original

    assert len(events) >= 33, "the fixture did not produce a long history"
    assert seen["n"] <= 12, (
        f"a {len(events)}-event history cost {seen['n']} queries — the merge is reading per "
        f"event rather than per source")
