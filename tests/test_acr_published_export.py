"""Exporting a PUBLISHED revision: the frozen record, and the digest as a gate rather than a field.

WHAT THIS ADDS TO THE EXPORT ALREADY SHIPPED. `/preview?format=pdf` renders the LIVE criteria
rows, and those keep moving after publication — a revision is opened, decisions carry, evidence
goes stale. Sending a customer "the published ACR" by exporting the draft is how they receive a
document that does not match the revision it names. Every document here is built from the
immutable snapshot instead.

WHY THE DIGEST IS A GATE HERE AND A FIELD ELSEWHERE. `/revisions` and `/revisions/{n}` report
`digest_verified` beside the content and let the reader judge, which is right for a JSON caller
who can see the flag next to the data. A PDF is the form in which a tampered snapshot travels
furthest before anyone notices: it leaves the application, and its holder has only the document.
So this endpoint refuses to build one at all — `test_a_tampered_snapshot_is_never_rendered` is the
test in this file whose failure would matter most.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pytest.importorskip("weasyprint")

import acr_export_pdf  # noqa: E402
import acr_export_preview  # noqa: E402
import acr_publish  # noqa: E402

OWNER = "owner@acp.test"
APPROVER = "approver@acp.test"
ANALYST = "analyst@acp.test"


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
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, APPROVER, ANALYST))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def published(client, isolated_store):
    """A report driven to publishable and published, returning its id.

    Decisions go through the store rather than 55 HTTP round trips, but publication itself goes
    through POST /publish so the real gate runs and the snapshot is written by the real code.
    """
    import acr_catalog

    rid = client(OWNER).post("/acr", json={"product_version": "1.4.0",
                                           "build_id": "b-900"}).json()["report_id"]
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": ANALYST, "role": "editor"})
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": APPROVER, "role": "approver"})

    isolated_store.update_acr_report_metadata(rid, owner_email=OWNER, fields={
        "report_title": "ACP ACR", "product_name": "ACP by Movate", "product_version": "1.4.0",
        "vendor_name": "Movate", "vendor_contact": "a11y@movate.test",
        "evaluation_scope": "The ACP web application.",
        "evaluation_methods": "axe-core plus guided manual test plans.",
        "browsers_tested": "Firefox 128", "operating_systems_tested": "Windows 11",
        "assistive_technologies_tested": "NVDA 2024.4", "automated_tools": "axe-core 4.12.1",
        "testing_period_start": "2026-08-01", "testing_period_end": "2026-08-31",
        "evaluators": ANALYST, "deployment_environment": "staging",
        "vpat_edition": "VPAT 2.5Rev WCAG", "wcag_version": "2.2", "wcag_levels": "A, AA",
        "product_description": "Document accessibility remediation platform.",
        "release_date": "2026-08-31", "excluded_functionality": "",
        "general_notes": "", "known_dependencies": "",
    })
    for num in acr_catalog.numbers():
        isolated_store.save_acr_decision(rid, num, owner_email=OWNER,
                                         final_status="Not Applicable",
                                         remarks="Out of scope for this evaluation.",
                                         decided_by=ANALYST)
        isolated_store.approve_acr_criterion(rid, num, owner_email=OWNER, reviewer=APPROVER)

    r = client(APPROVER).post(f"/acr/{rid}/publish")
    assert r.status_code == 200, r.text[:400]
    return rid


def _flat(pdf_bytes: bytes, tmp_path) -> str:
    """Extracted text with whitespace collapsed. pdfminer breaks lines mid-phrase, so a wrapped
    phrase is absent from the raw extraction while perfectly visible to a reader."""
    path = tmp_path / "published.pdf"
    path.write_bytes(pdf_bytes)
    from pdfminer.high_level import extract_text
    return re.sub(r"\s+", " ", extract_text(str(path)))


# ── the download ───────────────────────────────────────────────────────────────

def test_a_published_revision_downloads_as_a_tagged_pdf(client, published, tmp_path):
    """End to end over HTTP, as a person sending an ACR to a customer actually does it."""
    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export")
    assert r.status_code == 200, r.text[:400]
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF-")

    disp = r.headers.get("content-disposition", "")
    assert "attachment" in disp and published in disp, disp
    # The revision is in the filename because a procurement file collects several of these and
    # two revisions of one report downloading under the same name is how the wrong one is sent.
    assert "-rev1.pdf" in disp, disp


def test_the_document_states_its_revision_and_its_digest(client, published, tmp_path):
    """A published PDF that does not say which revision it is cannot be checked against anything.
    The digest is printed in full: a truncated one cannot be recomputed and compared."""
    detail = client(ANALYST).get(f"/acr/{published}/revisions/1").json()
    digest = detail["content_digest"]
    assert len(digest) == 64

    pdf = client(ANALYST).get(f"/acr/{published}/revisions/1/export").content
    text = _flat(pdf, tmp_path)

    assert "Published revision 1" in text, text[:600]
    assert digest in text, "the full digest must be in the document, not a prefix of it"
    assert "immutable published record" in text
    assert APPROVER in text, "the document does not say who published it"


def test_the_document_refuses_to_call_its_digest_a_signature(client, published, tmp_path):
    """A bare 64-hex string on a conformance document reads as a signature to almost everyone who
    is not told otherwise, and `api/report.py` and `acr_publish` both carry this same warning."""
    text = _flat(client(ANALYST).get(f"/acr/{published}/revisions/1/export").content, tmp_path)
    assert "not a digital signature" in text, text[:600]
    assert "never who produced it" in text


def test_the_published_export_carries_the_limitations_notice_too(client, published, tmp_path):
    """The published document travels further than the draft, so the disclosure matters more here,
    not less. Its absence would be a plausible oversight: this path composes its own HTML."""
    text = _flat(client(ANALYST).get(f"/acr/{published}/revisions/1/export").content, tmp_path)
    assert "Limitations of this document" in text, text[:600]
    assert "PAC 2024" in text


# ── the gate ───────────────────────────────────────────────────────────────────

def test_a_tampered_snapshot_is_never_rendered(client, published, isolated_store):
    """THE test in this file. A PDF is the form in which an altered record travels furthest, so
    the endpoint refuses to build one rather than building one that reports the problem inside."""
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(
            cur, "UPDATE acr_snapshot SET content_json=%s WHERE report_id=%s",
            ('{"schema":"acp.acr.snapshot/1","criteria":[],"totals":{"total":0}}', published))

    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export")
    assert r.status_code == 409, r.status_code
    assert not r.content.startswith(b"%PDF-"), "a document was produced from an altered snapshot"
    assert "altered since publication" in r.json()["detail"]

    # The JSON surfaces still serve it with the flag — the asymmetry is deliberate, and asserting
    # it here stops a later change "fixing" the inconsistency by making both refuse or both serve.
    assert client(ANALYST).get(f"/acr/{published}/revisions/1").json()["digest_verified"] is False


def test_an_unpublished_revision_is_a_404_not_an_empty_document(client, published):
    r = client(ANALYST).get(f"/acr/{published}/revisions/7/export")
    assert r.status_code == 404
    assert "no published revision 7" in r.json()["detail"]


def test_a_deployment_that_cannot_tag_refuses_rather_than_serving_an_untagged_pdf(
        client, published, monkeypatch):
    """The same fail-closed rule the draft export follows. An untagged conformance report is
    indistinguishable from a tagged one to everyone except the reader it exists for."""
    def boom(_html):
        raise acr_export_pdf.RendererUnavailable(acr_export_pdf.MISSING_RENDERER)

    monkeypatch.setattr(acr_export_pdf, "render_html", boom)
    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export")
    assert r.status_code == 503
    assert "weasyprint" in r.text.lower()
    assert not r.content.startswith(b"%PDF-")


# ── the frozen record, not today's draft ───────────────────────────────────────

def test_the_export_renders_the_snapshot_and_not_the_current_draft(
        client, published, isolated_store):
    """THE REASON THIS ENDPOINT EXISTS, and the one thing `/preview?format=pdf` cannot do.

    After publication the report moves on: a revision opens, decisions are re-made, evidence goes
    stale. If the published export read live rows, the document a customer receives as "revision
    1" would silently become whatever the draft says today — a conformance claim about a build
    nobody published, wearing a revision number somebody did.

    THE LIVE ROWS OF **THIS** REPORT ARE WHAT MOVE, and that is why the mutation below is applied
    to the published report itself rather than to a revision opened from it. An earlier version of
    this test opened a revision, changed a decision in the NEW report, and asserted the export was
    unchanged — which it was, and would have been even if the route read live rows, because those
    belong to a different report id. Swapping the route to read live criteria left the test GREEN.
    A test that cannot fail is indistinguishable from one that passed.
    """
    import acr_catalog

    first = acr_catalog.numbers()[0]
    before = client(ANALYST).get(f"/acr/{published}/revisions/1/export",
                                 params={"format": "html"}).text
    assert "Not Applicable: 55" in before

    # Move the live rows of the published report itself, through the store — deliberately below
    # the route guards, because the point is what the EXPORT reads, not what the API permits.
    for num in acr_catalog.numbers():
        isolated_store.save_acr_decision(published, num, owner_email=OWNER,
                                         final_status="Does Not Support",
                                         remarks="Regressed in 1.5.0.", decided_by=ANALYST)

    live = client(ANALYST).get(f"/acr/{published}/preview").json()["totals"]
    assert live["Does Not Support"] == 55, "the live rows did not actually move"

    after = client(ANALYST).get(f"/acr/{published}/revisions/1/export",
                                params={"format": "html"}).text
    assert after == before, "the published revision changed when the live rows did"
    assert "Regressed in 1.5.0" not in after
    # Through the totals rather than the bare phrase: the caption prints all four terms with their
    # counts, so "Does Not Support" appears in every export by construction.
    assert "Does Not Support: 0" in after and "Not Applicable: 55" in after


def test_the_html_and_pdf_forms_of_a_published_revision_cannot_disagree(
        client, published, tmp_path):
    """Both come from one `published_html` composition. Two call sites assembling the same three
    steps is how one ends up with two disclosures and the other with one."""
    html = client(ANALYST).get(f"/acr/{published}/revisions/1/export",
                               params={"format": "html"}).text
    pdf_text = _flat(client(ANALYST).get(f"/acr/{published}/revisions/1/export").content, tmp_path)

    for phrase in ("Published revision 1", "not a digital signature",
                   "Limitations of this document", "PAC 2024"):
        assert phrase in html, f"missing from the HTML form: {phrase}"
        assert phrase in pdf_text, f"missing from the PDF form: {phrase}"


# ── rehydration, as a unit ─────────────────────────────────────────────────────

def _content(**over) -> dict:
    base = {
        "schema": "acp.acr.snapshot/1",
        "catalog_hash": "abc123",
        "report": {"report_title": "ACP ACR", "product_name": "ACP", "product_version": "1.4.0"},
        "criteria": [{
            "criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA",
            "conformance_level": "Supports", "remarks": "Measured at 7:1.",
            "evaluator": ANALYST, "reviewer": APPROVER, "approved_at": "2026-08-31T00:00:00Z",
            "evidence": {"total": 2, "automated": 1, "manual": 1, "ids": ["e1", "e2"]},
        }],
        "totals": {"total": 1, "Supports": 1, "undecided": 0},
    }
    base.update(over)
    return base


def test_rehydration_maps_the_snapshot_column_onto_the_conformance_cell():
    """The snapshot calls it `conformance_level` and `project()` calls it `final_status`. A
    mismatch here renders every published criterion as "not yet evaluated" — a document that
    understates the report rather than failing, which is the direction that ships."""
    report, criteria, ev = acr_publish.projection_inputs(_content())
    projection = acr_export_preview.project(report, criteria, evidence_by_criterion=ev,
                                            stale_ids=set())
    row = projection["criteria"][0]
    assert row["conformance_level"] == "Supports"
    assert row["remarks"] == "Measured at 7:1."
    assert row["evidence_live"] == 2, "the evidence the snapshot recorded is not being counted"
    assert row["evidence_stale"] == 0


def test_rehydration_marks_the_report_published_rather_than_leaving_it_a_draft():
    report, _, _ = acr_publish.projection_inputs(_content())
    assert report["status"] == "published"
    assert report["catalog_hash"] == "abc123"


def test_rehydration_never_injects_todays_draft_suggestion():
    """`draft_status` is ACP's own guess for an undecided criterion. A published revision has
    none, and putting today's into a record a human signed would be a machine's opinion presented
    as part of an approved document."""
    _, criteria, _ = acr_publish.projection_inputs(_content())
    assert criteria[0]["draft_status"] is None


def test_a_criterion_the_catalog_no_longer_carries_is_still_exported():
    """PRD §19 forbids concealing failures, and a catalog advance is not an exemption. The claim
    was published; it stays published after WCAG moves on, losing only its principle grouping."""
    content = _content(criteria=[{
        "criterion_num": "9.9.9", "criterion_name": "Retired Criterion", "level": "AA",
        "conformance_level": "Does Not Support", "remarks": "A real barrier.",
        "evidence": {"total": 0, "ids": []},
    }])
    _, criteria, _ = acr_publish.projection_inputs(content)
    assert len(criteria) == 1
    assert criteria[0]["final_status"] == "Does Not Support"
    assert criteria[0]["principle"] is None


def test_evidence_counts_survive_a_snapshot_written_before_ids_were_stored():
    """The count is the fact a reader needs. Losing it because the identifiers are absent would
    understate what stood behind a published claim."""
    content = _content(criteria=[{
        "criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA",
        "conformance_level": "Supports", "remarks": "",
        "evidence": {"total": 3, "automated": 3, "manual": 0},
    }])
    _, _, ev = acr_publish.projection_inputs(content)
    assert len(ev["1.4.3"]) == 3
    assert len({e.id for e in ev["1.4.3"]}) == 3, "stand-ins must be distinguishable"


def test_the_provenance_block_refuses_html_it_cannot_anchor_to():
    """Same discipline as `with_limitations`: a silently unmodified return ships a
    published-looking conformance report that never says which revision it is."""
    with pytest.raises(ValueError, match="publication provenance"):
        acr_export_pdf.with_provenance("<p>no heading</p>", revision=1, digest="d",
                                       published_at="t", published_by="p", verified=True)


def test_an_unverified_render_says_so_in_the_document():
    """The route refuses before reaching here, so this branch is unreachable today. It exists so
    that a future caller who renders without checking produces a document that visibly says the
    digest was not verified, rather than one that quietly omits the question."""
    html = acr_export_pdf.with_provenance("<h1>t</h1>", revision=2, digest="d",
                                          published_at="t", published_by="p", verified=False)
    assert "NOT verified" in html
