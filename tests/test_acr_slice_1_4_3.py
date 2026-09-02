"""The Phase 1 vertical slice, end to end over HTTP: WCAG 1.4.3 Contrast (Minimum), AA.

One criterion, the whole path the PRD describes — automated evidence attaches, manual evidence
attaches, the coverage rule refuses to draft "Supports" from the automated row alone, a human
selects the final status, an approver signs it off, validation reports what is still missing, and
the criterion appears in a draft structural export.

WHY 1.4.3 AND NOT A SIMPLER ONE. PRD §23 says to use real evidence rather than fabricated demo
results. 1.4.3 is the criterion where ACP genuinely has an automated check against its OWN UI —
frontend/src/ownContrast.test.js exists and axe-core's `color-contrast` rule runs over ACP's
screens in A11ySelfCheck.jsx. So the automated evidence in this test is shaped like a real axe
result (tool, version, rule id, the URL tested), not an invented one.

The rule-level tests live in test_acr_decision_rules.py. This file is about the wiring: that the
rules are actually reached through the HTTP layer, in order, against a real store.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

SC = "1.4.3"
OWNER = "owner@acp.test"
ANALYST = "analyst@acp.test"
APPROVER = "approver@acp.test"


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
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ANALYST, APPROVER))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def report(client):
    """A report with complete metadata and the two collaborators PRD §18 wants."""
    import acr_validation as V
    meta = {f: f"{f}-value" for f in V.REQUIRED_METADATA}
    meta.update({f: f"{f}-value" for f in V.ADVISORY_METADATA})
    meta.update({"product_name": "ACP by Movate", "product_version": "1.4.0",
                 "build_id": "b-900", "wcag_version": "2.2", "wcag_levels": "A, AA",
                 "vpat_edition": "VPAT 2.5Rev WCAG"})
    rid = client(OWNER).post("/acr", json={"metadata": meta}).json()["report_id"]
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": ANALYST, "role": "editor"})
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": APPROVER, "role": "approver"})
    return rid


def _axe(client, rid, user=ANALYST, result="pass"):
    """An axe-core result, shaped the way a real one is (PRD §13: preserve the tool, version,
    rule id, tested view and original result)."""
    return client(user).post(f"/acr/{rid}/criteria/{SC}/evidence", json={
        "criterion_num": SC, "source_kind": "automated", "result": result,
        "tool_name": "axe-core", "tool_version": "4.12.1", "rule_id": "color-contrast",
        "tested_url": "/assess", "coverage": "partial",
        "method": "axe-core run over the Assess view", "workflow": "assess"})


def _manual(client, rid, user=ANALYST, result="pass"):
    return client(user).post(f"/acr/{rid}/criteria/{SC}/evidence", json={
        "criterion_num": SC, "source_kind": "manual", "result": result,
        "method": "sampled text/background pairs with a contrast analyser",
        "browser": "Chromium 141", "environment": "staging", "workflow": "assess",
        "notes": "checked body text, muted labels and disabled controls"})


# ── the matrix ────────────────────────────────────────────────────────────────────────────────

def test_a_new_report_has_the_whole_wcag_22_matrix(client, report):
    body = client(OWNER).get(f"/acr/{report}").json()
    assert body["progress"]["total"] == 55
    assert body["progress"]["decided"] == 0
    assert body["progress"]["undecided"] == 55

    crit = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()
    assert crit["criterion"]["level"] == "AA"
    assert crit["criterion"]["criterion_name"] == "Contrast (Minimum)"
    assert crit["criterion"]["workflow_state"] == "not_evaluated"
    assert crit["criterion"]["final_status"] is None


# ── PRD §4.3, over HTTP ───────────────────────────────────────────────────────────────────────

def test_an_axe_pass_alone_does_not_draft_or_permit_supports(client, report):
    r = _axe(client, report)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["draft_status"] is None
    assert "coverage=partial" in body["draft_reason"]
    assert body["assessment"]["permitted_statuses"]["Supports"] is False
    assert "automated evidence alone" in body["assessment"]["refusals"]["Supports"]

    # And the decision endpoint actually enforces it, with the rule's own sentence.
    d = client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                             json={"final_status": "Supports"})
    assert d.status_code == 422
    assert "automated evidence alone" in d.json()["detail"]


def test_the_original_automated_result_is_preserved(client, report):
    """PRD §13: "Preserve the original rule ID and result"."""
    _axe(client, report)
    ev = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()["evidence"]
    assert len(ev) == 1
    assert ev[0]["tool_name"] == "axe-core"
    assert ev[0]["tool_version"] == "4.12.1"
    assert ev[0]["rule_id"] == "color-contrast"
    assert ev[0]["tested_url"] == "/assess"
    assert ev[0]["result"] == "pass"
    assert ev[0]["coverage"] == "partial"


def test_evidence_inherits_the_reports_product_version(client, report):
    """Evidence with no version cannot be freshness-checked against the report at all, so an
    omitted one would silently produce evidence that never goes stale."""
    _axe(client, report)
    ev = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()["evidence"][0]
    assert ev["product_version"] == "1.4.0"
    assert ev["build_id"] == "b-900"


# ── the human completes it ────────────────────────────────────────────────────────────────────

def test_manual_evidence_unlocks_supports_and_records_the_environment(client, report):
    """PRD §21.5 — manual results carry environment and tester details."""
    _axe(client, report)
    r = _manual(client, report)
    assert r.status_code == 200, r.text
    assert r.json()["draft_status"] == "Supports"

    detail = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()
    manual = [e for e in detail["evidence"] if e["source_kind"] == "manual"][0]
    assert manual["tester"] == ANALYST
    assert manual["browser"] == "Chromium 141"
    assert manual["environment"] == "staging"
    assert detail["assessment"]["permitted_statuses"]["Supports"] is True

    d = client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                             json={"final_status": "Supports"})
    assert d.status_code == 200, d.text
    crit = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()["criterion"]
    assert crit["final_status"] == "Supports"
    assert crit["workflow_state"] == "decided"
    assert crit["evaluator"] == ANALYST


def test_a_draft_suggestion_never_becomes_a_decision_on_its_own(client, report):
    """PRD §20: a model may draft, never select. Even a drafted "Supports" leaves the criterion
    in needs_review with final_status unset until a person posts a decision."""
    _axe(client, report)
    _manual(client, report)
    crit = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()["criterion"]
    assert crit["draft_status"] == "Supports"
    assert crit["final_status"] is None
    assert crit["workflow_state"] == "needs_review"


# ── PRD §21.7 / §21.8 over HTTP ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["Partially Supports", "Does Not Support", "Not Applicable"])
def test_the_limitation_statuses_are_refused_without_remarks(client, report, status):
    _axe(client, report)
    _manual(client, report)
    bad = client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                               json={"final_status": status})
    assert bad.status_code == 422
    assert "remarks" in bad.json()["detail"]

    ok = client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                              json={"final_status": status, "remarks": "the real explanation"})
    assert ok.status_code == 200, ok.text


def test_an_unresolved_failure_blocks_a_supports_decision(client, report):
    _axe(client, report)
    _manual(client, report)
    _manual(client, report, result="fail")
    r = client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                             json={"final_status": "Supports"})
    assert r.status_code == 422
    assert "unresolved failure" in r.json()["detail"]


def test_newer_passing_evidence_resolves_it(client, report):
    _axe(client, report)
    _manual(client, report, result="fail")
    _manual(client, report, result="pass")
    r = client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                             json={"final_status": "Supports"})
    assert r.status_code == 200, r.text


# ── approval, validation, audit ───────────────────────────────────────────────────────────────

def test_approval_records_the_reviewer_separately_from_the_evaluator(client, report):
    """PRD §18's separation of duties, visible in the record: the person who decided and the
    person who signed off are two different columns."""
    _axe(client, report)
    _manual(client, report)
    client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision", json={"final_status": "Supports"})
    r = client(APPROVER).post(f"/acr/{report}/criteria/{SC}/approve")
    assert r.status_code == 200, r.text

    crit = client(OWNER).get(f"/acr/{report}/criteria/{SC}").json()["criterion"]
    assert crit["evaluator"] == ANALYST
    assert crit["reviewer"] == APPROVER
    assert crit["approval_state"] == "approved"


def test_a_criterion_with_no_decision_cannot_be_approved(client, report):
    r = client(APPROVER).post(f"/acr/{report}/criteria/{SC}/approve")
    assert r.status_code == 422


def test_validation_blocks_publication_and_says_why(client, report):
    """PRD §21.10 — 54 of 55 criteria are still unevaluated after the slice, so the report cannot
    publish however complete 1.4.3 is. That is the point: an ACR is all-or-nothing."""
    _axe(client, report)
    _manual(client, report)
    client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision", json={"final_status": "Supports"})
    client(APPROVER).post(f"/acr/{report}/criteria/{SC}/approve")

    v = client(OWNER).get(f"/acr/{report}/validation").json()
    assert v["summary"]["may_publish"] is False
    assert v["summary"]["by_category"]["missing_decision"] == 54
    # 1.4.3 itself is clean — it is not among the blockers.
    blocked = {row["criterion_num"] for rows in v["by_category"].values() for row in rows}
    assert SC not in blocked


def test_the_audit_trail_records_every_consequential_step(client, report):
    """PRD §17."""
    _axe(client, report)
    _manual(client, report)
    client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision", json={"final_status": "Supports"})
    client(APPROVER).post(f"/acr/{report}/criteria/{SC}/approve")

    events = client(OWNER).get(f"/acr/{report}/audit").json()["events"]
    actions = [e["action"] for e in events]
    assert "report.created" in actions
    assert actions.count("evidence.added") == 2
    assert "criterion.decided" in actions
    assert "criterion.approved" in actions
    assert "role.granted" in actions
    decided = [e for e in events if e["action"] == "criterion.decided"][0]
    assert decided["actor"] == ANALYST and decided["criterion_num"] == SC


# ── the draft export ──────────────────────────────────────────────────────────────────────────

def test_the_criterion_appears_in_the_draft_export_with_its_conformance_level(client, report):
    _axe(client, report)
    _manual(client, report)
    client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision", json={"final_status": "Supports"})

    proj = client(OWNER).get(f"/acr/{report}/preview").json()
    assert len(proj["criteria"]) == 55
    row = [r for r in proj["criteria"] if r["criterion_num"] == SC][0]
    assert row["conformance_level"] == "Supports"
    assert row["level"] == "AA"
    assert row["principle"] == "Perceivable"
    assert proj["totals"]["Supports"] == 1
    assert proj["totals"]["undecided"] == 54


def test_the_export_never_prints_an_internal_state_as_a_conformance_level(client, report):
    """PRD §9. An undecided criterion renders a marker that cannot be mistaken for a VPAT term."""
    proj = client(OWNER).get(f"/acr/{report}/preview").json()
    levels = {r["conformance_level"] for r in proj["criteria"]}
    assert levels == {"— not yet evaluated —"}
    assert not levels & {"not_evaluated", "needs_review", "decided"}


def test_the_preview_says_it_is_not_a_vpat(client, report):
    """The ITI template is Phase 5 and gated on a licensing decision. A preview that looked like
    a finished VPAT would be the most consequential thing in this feature to get wrong."""
    proj = client(OWNER).get(f"/acr/{report}/preview").json()
    assert proj["template"]["is_official_iti_template"] is False
    assert "not a VPAT" in proj["template"]["note"]

    html = client(OWNER).get(f"/acr/{report}/preview?format=html").text
    assert "Draft structural preview" in html
    assert 'lang="en"' in html
    assert "<caption>" in html
    assert 'scope="col"' in html and 'scope="row"' in html


def test_the_export_reports_counts_and_never_a_compliance_score(client, report):
    """PRD §4.4 — ACP must not optimize for a misleading compliance score. ADR 0016/0023's
    "counts only, never a percentage of an invented denominator" applies here too."""
    proj = client(OWNER).get(f"/acr/{report}/preview").json()
    for key, value in proj["totals"].items():
        assert isinstance(value, int), key
    assert not any("pct" in k or "percent" in k or "score" in k for k in proj["totals"])


# ── immutability of a published report is enforced at the edit boundary ───────────────────────

def test_a_published_report_refuses_edits(client, report, isolated_store):
    """PRD §17/§21.12. Publication itself is Phase 4; this pins the edit boundary the snapshot
    depends on, so a later publish endpoint cannot be the only thing holding it."""
    import acr_catalog
    isolated_store.create_acr_snapshot(
        "snap1", report_id=report, owner_email=OWNER, revision=1,
        catalog_hash=acr_catalog.catalog_hash(), content_json="{}", content_digest="d",
        published_by=APPROVER)

    assert client(ANALYST).patch(f"/acr/{report}",
                                 json={"fields": {"report_title": "x"}}).status_code == 409
    assert _axe(client, report).status_code == 409
    assert client(ANALYST).post(f"/acr/{report}/criteria/{SC}/decision",
                                json={"final_status": "Supports"}).status_code == 409
