"""Publication over HTTP (PRD §16, §21.11, §21.12) — Phase 4.

The unit rules are in test_acr_publish.py. This file is the gate: that publication is REFUSED for
the right reasons, allowed only when it should be, and that what it produces cannot afterwards be
edited. Publication is the one irreversible act in this feature, so these are the tests whose
failure would matter most.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

# Category names come from the module that defines them, never retyped: an assertion on a
# guessed string passes or fails for reasons unrelated to the behaviour it describes.
import acr_validation  # noqa: E402

OWNER = "owner@acp.test"
APPROVER = "approver@acp.test"
ANALYST = "analyst@acp.test"
RANDOM = "random@acp.test"


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
    # OPEN_ACCESS is True on purpose: it is the configuration the publish gate exists to survive.
    # Under it core.is_admin() returns True for every authenticated user, so a gate built on
    # is_admin would admit anybody while passing a naive test.
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed",
                        lambda e: e in (OWNER, APPROVER, ANALYST, RANDOM))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def report(client):
    rid = client(OWNER).post("/acr", json={"product_version": "1.4.0",
                                           "build_id": "b-900"}).json()["report_id"]
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": ANALYST, "role": "editor"})
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": APPROVER, "role": "approver"})
    return rid


def _publishable(client, report, isolated_store):
    """Drive a report all the way to publishable, through the real endpoints where possible.

    Metadata and decisions go through the store rather than 55 HTTP round trips — but the GATE is
    never bypassed: the test still calls POST /publish and the endpoint still recomputes every
    blocker for itself.
    """
    import acr_catalog

    isolated_store.update_acr_report_metadata(report, owner_email=OWNER, fields={
        "report_title": "ACP ACR", "product_name": "ACP by Movate", "product_version": "1.4.0",
        "vendor_name": "Movate", "vendor_contact": "a11y@movate.test",
        "evaluation_scope": "The ACP web application.",
        "evaluation_methods": "axe-core plus guided manual test plans.",
        "browsers_tested": "Firefox 128", "operating_systems_tested": "Windows 11",
        "assistive_technologies_tested": "NVDA 2024.4", "automated_tools": "axe-core 4.12.1",
        "testing_period_start": "2026-08-01", "testing_period_end": "2026-08-31",
        "evaluators": "analyst@acp.test", "deployment_environment": "staging",
        "vpat_edition": "VPAT 2.5Rev WCAG", "wcag_version": "2.2", "wcag_levels": "A, AA",
        "product_description": "Document accessibility remediation platform.",
        "release_date": "2026-08-31", "excluded_functionality": "",
        "general_notes": "", "known_dependencies": "",
    })
    for num in acr_catalog.numbers():
        isolated_store.save_acr_decision(report, num, owner_email=OWNER,
                                         final_status="Not Applicable",
                                         remarks="Out of scope for this evaluation.",
                                         decided_by=ANALYST)
        isolated_store.approve_acr_criterion(report, num, owner_email=OWNER, reviewer=APPROVER)
    return report


# ── the gate ───────────────────────────────────────────────────────────────────

def test_publication_is_refused_while_any_blocker_stands(client, report):
    """PRD §21.10. A fresh report has 55 unevaluated criteria; that it cannot publish is the whole
    point of an all-or-nothing conformance report."""
    r = client(APPROVER).post(f"/acr/{report}/publish")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "blocker(s) prevent publication" in detail["message"]
    assert detail["blockers"], "the refusal must say WHICH blockers, not merely that there are some"


def test_a_non_approver_cannot_publish_even_under_open_access(client, report, isolated_store):
    """PRD §21.11, and the asymmetry Phase 1 introduced deliberately.

    OPEN_ACCESS=1 makes core.is_admin() True for every authenticated user, so a gate built on it
    would satisfy "only an approver may publish" on paper and not at all in fact. The editor here
    has a real role and still cannot publish.
    """
    _publishable(client, report, isolated_store)
    assert client(ANALYST).post(f"/acr/{report}/publish").status_code == 403
    assert client(RANDOM).post(f"/acr/{report}/publish").status_code == 403


def test_the_role_check_runs_before_the_readiness_check(client, report):
    """An unauthorized caller must learn nothing about the report's internal readiness — a 400
    listing every outstanding blocker would leak exactly that."""
    r = client(RANDOM).post(f"/acr/{report}/publish")
    assert r.status_code == 403
    assert "blocker" not in r.text.lower()


def test_an_approver_can_publish_a_clean_report(client, report, isolated_store):
    """The other half. A gate that can never be satisfied is as broken as one that never fires."""
    _publishable(client, report, isolated_store)
    r = client(APPROVER).post(f"/acr/{report}/publish")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == 1
    assert len(body["content_digest"]) == 64
    # The response says what the digest is and is not, so an API log cannot imply a signature.
    assert "not a digital signature" in body["digest_note"]


def test_publishing_twice_is_refused(client, report, isolated_store):
    _publishable(client, report, isolated_store)
    assert client(APPROVER).post(f"/acr/{report}/publish").status_code == 200
    r = client(APPROVER).post(f"/acr/{report}/publish")
    assert r.status_code == 409
    assert "already published" in r.json()["detail"]


def test_a_published_report_refuses_every_edit(client, report, isolated_store):
    """PRD §17/§21.12 — the immutability boundary, now reached through the real publish endpoint
    rather than by writing a snapshot row directly as Phase 1's test had to."""
    _publishable(client, report, isolated_store)
    assert client(APPROVER).post(f"/acr/{report}/publish").status_code == 200

    assert client(ANALYST).patch(f"/acr/{report}",
                                 json={"fields": {"report_title": "x"}}).status_code == 409
    assert client(ANALYST).post(f"/acr/{report}/criteria/1.4.3/decision",
                                json={"final_status": "Supports"}).status_code == 409
    assert client(ANALYST).post(f"/acr/{report}/criteria/1.4.3/plans/start",
                                json={"plan_id": "contrast"}).status_code == 409


# ── the published artifact ─────────────────────────────────────────────────────

def test_the_snapshot_verifies_against_its_own_digest(client, report, isolated_store):
    """Verified on every read rather than on demand: a tamper-evident record nobody checks is a
    record nobody has checked."""
    _publishable(client, report, isolated_store)
    client(APPROVER).post(f"/acr/{report}/publish")

    revs = client(ANALYST).get(f"/acr/{report}/revisions").json()
    assert len(revs["revisions"]) == 1
    assert revs["revisions"][0]["digest_verified"] is True
    assert revs["revisions"][0]["digest_problem"] == ""

    detail = client(ANALYST).get(f"/acr/{report}/revisions/1").json()
    assert detail["digest_verified"] is True
    assert detail["content"]["totals"]["total"] == 55


def test_a_tampered_snapshot_is_reported_as_altered_rather_than_served_quietly(
        client, report, isolated_store):
    """The failure mode the digest exists for. Altering the stored content must surface on the
    next read, not wait for someone to think to check."""
    _publishable(client, report, isolated_store)
    client(APPROVER).post(f"/acr/{report}/publish")

    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(
            cur, "UPDATE acr_snapshot SET content_json=%s WHERE report_id=%s",
            ('{"schema":"acp.acr.snapshot/1","criteria":[],"totals":{"total":0}}', report))

    row = client(ANALYST).get(f"/acr/{report}/revisions").json()["revisions"][0]
    assert row["digest_verified"] is False
    assert "altered since publication" in row["digest_problem"]


# ── revisions ──────────────────────────────────────────────────────────────────

def test_a_draft_cannot_be_revised(client, report):
    r = client(ANALYST).post(f"/acr/{report}/revise")
    assert r.status_code == 409
    assert "still a draft" in r.json()["detail"]


def test_revising_opens_a_new_draft_that_supersedes_the_published_one(
        client, report, isolated_store):
    _publishable(client, report, isolated_store)
    client(APPROVER).post(f"/acr/{report}/publish")

    r = client(ANALYST).post(f"/acr/{report}/revise")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == 2
    assert body["supersedes_id"] == report

    new = client(ANALYST).get(f"/acr/{body['report_id']}").json()["report"]
    assert new["status"] == "draft"
    assert new["revision"] == 2
    # The published one is untouched.
    old = client(ANALYST).get(f"/acr/{report}").json()["report"]
    assert old["status"] == "published"


def test_no_approval_survives_into_the_revision(client, report, isolated_store):
    """PRD §4.2. Every criterion of the previous revision was approved; none of that carries,
    because an approval granted for the previous product version is not a sign-off on this one."""
    _publishable(client, report, isolated_store)
    client(APPROVER).post(f"/acr/{report}/publish")
    new_id = client(ANALYST).post(f"/acr/{report}/revise").json()["report_id"]

    criteria = client(ANALYST).get(f"/acr/{new_id}/criteria").json()["criteria"]
    assert criteria, "the revision must have a full matrix"
    assert all(c["approval_state"] != "approved" for c in criteria)

    # …so the revision cannot publish either, until someone approves it again.
    r = client(APPROVER).post(f"/acr/{new_id}/publish")
    assert r.status_code == 400


def test_the_revision_history_spans_the_supersedes_chain(client, report, isolated_store):
    """A revision is a NEW report row, so "the history of this report" spans several ids. Reading
    only the current row's snapshots would show a one-entry history for a report on its third
    revision."""
    _publishable(client, report, isolated_store)
    client(APPROVER).post(f"/acr/{report}/publish")
    new_id = client(ANALYST).post(f"/acr/{report}/revise").json()["report_id"]

    revs = client(ANALYST).get(f"/acr/{new_id}/revisions").json()
    assert [r["revision"] for r in revs["revisions"]] == [1]
    assert [l["report_id"] for l in revs["lineage"]] == [new_id, report]


def test_publication_readiness_reports_the_same_refusal_the_endpoint_enforces(client, report):
    """The screen renders this; the endpoint enforces its own recomputation. If they disagreed,
    the UI would offer a publish button the server rejects."""
    readiness = client(APPROVER).get(f"/acr/{report}/publication").json()
    assert readiness["may_publish"] is False
    assert readiness["blocking_count"] > 0
    assert "cannot be edited or withdrawn" in readiness["irreversible_note"]

    r = client(APPROVER).post(f"/acr/{report}/publish")
    assert r.status_code == 400
    assert len(r.json()["detail"]["blockers"]) == readiness["blocking_count"]


def test_readiness_tells_a_non_approver_why_they_cannot_publish(client, report):
    readiness = client(ANALYST).get(f"/acr/{report}/publication").json()
    assert readiness["may_publish"] is False
    assert "not an approver" in readiness["role_refusal"]


def test_roles_carry_into_a_revision_but_approvals_do_not(client, report, isolated_store):
    """The distinction the revise flow turns on, pinned because both halves are easy to get wrong
    in opposite directions.

    A ROLE says "this person is authorized to approve on this report". An APPROVAL says "this
    person did approve this criterion, for this product version". Carrying the role is continuity —
    without it every revision would need an admin to re-grant every role before anyone could work,
    and the person revising may not be an admin. Carrying the approval would be a recorded
    sign-off that never happened.

    Found by test_no_approval_survives_into_the_revision failing with 403 rather than 400: the
    approver held no role on the new report id, so the revision could not have been published by
    anybody at all.
    """
    _publishable(client, report, isolated_store)
    client(APPROVER).post(f"/acr/{report}/publish")
    new_id = client(ANALYST).post(f"/acr/{report}/revise").json()["report_id"]

    # The role carried: the approver is recognised on the new report…
    assert "approver" in client(APPROVER).get(f"/acr/{new_id}/roles").json()["roles"]
    # …and so did the editor's, so work continues without an admin round trip.
    assert "editor" in client(ANALYST).get(f"/acr/{new_id}/roles").json()["roles"]

    # But nothing is approved, so publication is refused on READINESS (400), not on ROLE (403).
    r = client(APPROVER).post(f"/acr/{new_id}/publish")
    assert r.status_code == 400, r.text
    cats = {b["category"] for b in r.json()["detail"]["blockers"]}
    assert acr_validation.CATEGORY_UNAPPROVED in cats, sorted(cats)
