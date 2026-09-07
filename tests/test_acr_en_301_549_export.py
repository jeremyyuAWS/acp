"""Phase 6.4 — the EU report renders, against a catalog that does not exist yet.

THE ORDERING, WHICH IS THE POINT. 6.4 has two halves and only one of them is blocked: the
requirement text needs a licensing answer, the renderer needs nothing. So the renderer landed
first, and these tests prove it works by supplying a catalog of their own — two clauses, invented
here and going nowhere near `config/en-301-549.json`, which stays empty.

That distinction matters. A fixture that fabricates requirements to TEST a renderer is a test
fixture. A catalog that fabricates them to SHIP is the false claim PRD §19 forbids and #1532
found in production. These rows live in this file, are named as invented, and never reach the
committed catalog — `test_acr_en_301_549_stub.py` holds that one to being empty.

WHAT IS SHARED, AND WHY. `_grouped_section` and `_requirement_section_html` serve Section 508 and
EN 301 549 both, because the two differ only in what the division is called — a chapter in 36 CFR
1194, a clause in EN 301 549 — and in where its names come from. Two copies would be two places
for the honesty checks to drift: the undecided cell, the labelled draft suggestion, the stale
evidence note. The 508 assertions in test_acr_508_export.py and the EU ones here now exercise the
same code, which is the check that the sharing did not quietly change either.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402
import acr_export_preview  # noqa: E402

REPORT = {"report_title": "ACP ACR", "product_name": "ACP by Movate", "product_version": "1.4.0",
          "wcag_version": "2.2", "vpat_edition": acr_catalog.EDITION_EU, "vendor_name": "Movate"}

# Invented, for this test only. Real clause numbers and titles, so the shape is realistic; the
# committed catalog holds none of them.
FIXTURE = {
    "_meta": {
        "standard": "EN 301 549",
        "citation": "EN 301 549 V3.2.1 — Accessibility requirements for ICT products and services",
        "publisher": "CEN, CENELEC and ETSI",
        "clauses": {"9": {"name": "Web"}, "11": {"name": "Software"},
                    "12": {"name": "Documentation and support services"}},
    },
    "requirements": [
        {"num": "9.1.1.1", "name": "Non-text content", "clause": "9", "kind": "requirement"},
        {"num": "9.2.4.2", "name": "Page titled", "clause": "9", "kind": "requirement"},
        {"num": "11.7", "name": "User preferences", "clause": "11", "kind": "requirement"},
        {"num": "12.1.1", "name": "Accessibility and compatibility features", "clause": "12",
         "kind": "requirement"},
    ],
}


@pytest.fixture
def en_catalog(tmp_path, monkeypatch):
    """Supply a catalog without touching the committed one, and clear the reader's cache both
    ways — a stale lru_cache would leak these invented rows into every test that follows."""
    path = tmp_path / "en-301-549.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    monkeypatch.setattr(acr_catalog, "_EN_301_549_PATH", path)
    acr_catalog._load_en.cache_clear()
    yield path
    acr_catalog._load_en.cache_clear()


@pytest.fixture
def projection(en_catalog):
    matrix = acr_catalog.build_matrix("rep-eu", acr_catalog.EDITION_EU)
    return acr_export_preview.project(REPORT, matrix)


# ── the matrix ────────────────────────────────────────────────────────────────────────────────

def test_the_eu_edition_carries_wcag_and_en_rows(en_catalog):
    matrix = acr_catalog.build_matrix("rep-eu", acr_catalog.EDITION_EU)
    by_set: dict[str, int] = {}
    for row in matrix:
        by_set[row["requirement_set"]] = by_set.get(row["requirement_set"], 0) + 1
    assert by_set == {acr_catalog.REQ_WCAG: 55, acr_catalog.REQ_EN_301_549: 4}


def test_an_en_row_carries_its_clause_in_the_division_column(en_catalog):
    """`chapter` holds the division whatever the standard calls it — a chapter in 36 CFR 1194, a
    clause in EN 301 549. One column, because the projection groups on it either way and a second
    nullable column would be one more thing every renderer had to know about."""
    rows = [r for r in acr_catalog.build_matrix("rep-eu", acr_catalog.EDITION_EU)
            if r["requirement_set"] == acr_catalog.REQ_EN_301_549]
    assert {r["chapter"] for r in rows} == {"9", "11", "12"}
    assert all(r["level"] is None and r["principle"] is None for r in rows)


def test_the_int_edition_carries_all_three_sets(en_catalog):
    matrix = acr_catalog.build_matrix("rep-int", acr_catalog.EDITION_INT)
    by_set: dict[str, int] = {}
    for row in matrix:
        by_set[row["requirement_set"]] = by_set.get(row["requirement_set"], 0) + 1
    assert by_set == {acr_catalog.REQ_WCAG: 55, acr_catalog.REQ_SECTION_508: 120,
                      acr_catalog.REQ_EN_301_549: 4}


# ── the projection ────────────────────────────────────────────────────────────────────────────

def test_the_en_rows_are_grouped_into_clauses(projection):
    clauses = {c["num"]: c for c in projection["en_301_549"]["chapters"]}
    assert sorted(clauses) == ["11", "12", "9"]
    assert clauses["9"]["name"] == "Web"
    assert clauses["9"]["label"] == "Clause"
    assert len(clauses["9"]["rows"]) == 2


def test_the_totals_count_the_en_rows_too(projection):
    assert projection["totals"]["total"] == 59          # 55 WCAG + 4 EN
    assert projection["en_301_549"]["totals"]["total"] == 4


def test_the_citation_names_the_standard_and_its_publishers(projection):
    citation = projection["en_301_549"]["citation"]
    assert "EN 301 549" in citation
    assert "ETSI" in citation


def test_a_508_report_still_has_no_en_key():
    """Absent, not empty — the same rule the 508 section follows, so a renderer keying off
    presence cannot print a bare "EN 301 549 Report" heading over nothing."""
    proj = acr_export_preview.project(
        {"report_title": "x", "vpat_edition": acr_catalog.EDITION_508},
        acr_catalog.build_matrix("rep-508", acr_catalog.EDITION_508))
    assert "section_508" in proj
    assert "en_301_549" not in proj


def test_a_clause_the_catalog_does_not_name_renders_under_its_number(tmp_path, monkeypatch):
    unnamed = tmp_path / "en.json"
    unnamed.write_text(json.dumps({
        "_meta": {"standard": "EN 301 549", "clauses": {}},
        "requirements": [{"num": "13.1.2", "name": "Relay", "clause": "13",
                          "kind": "requirement"}],
    }), encoding="utf-8")
    monkeypatch.setattr(acr_catalog, "_EN_301_549_PATH", unnamed)
    acr_catalog._load_en.cache_clear()
    proj = acr_export_preview.project(
        REPORT, acr_catalog.build_matrix("rep-eu", acr_catalog.EDITION_EU))
    assert proj["en_301_549"]["chapters"][0]["name"] == "Clause 13"
    acr_catalog._load_en.cache_clear()


def test_an_internal_workflow_state_still_raises_on_an_en_row():
    """PRD §9's last line of defence reaches every row, whichever standard it came from."""
    rows = [{"criterion_num": "9.1.1.1", "criterion_name": "Non-text content", "chapter": "9",
             "requirement_set": acr_catalog.REQ_EN_301_549, "final_status": "needs_review"}]
    with pytest.raises(ValueError) as e:
        acr_export_preview.project({"report_title": "x"}, rows)
    assert "9.1.1.1" in str(e.value)
    assert "internal workflow state" in str(e.value)


# ── the HTML, which the PDF export renders from unchanged ─────────────────────────────────────

def test_the_html_prints_an_eu_report_with_clause_tables(projection):
    html = acr_export_preview.to_html(projection)
    assert "EN 301 549 Report" in html
    # The template's wording for the EU edition — clause 9 carries its cross-reference, and the
    # template writes title case where the standard (and so ACP's catalog) writes sentence case.
    for caption in ("Clause 9: Web (see WCAG 2.x section)", "Clause 11: Software",
                    "Clause 12: Documentation and Support Services"):
        assert caption in html, caption
    assert "9.1.1.1 Non-text content" in html
    assert "11.7 User preferences" in html


def test_the_clause_tables_carry_no_level_column(projection):
    html = acr_export_preview.to_html(projection)
    after = html.split("EN 301 549 Report", 1)[1]
    assert '<th scope="col">Level</th>' not in after
    assert after.count('<th scope="col">Conformance Level</th>') == 3


def test_every_en_row_is_a_row_header(projection):
    html = acr_export_preview.to_html(projection)
    after = html.split("EN 301 549 Report", 1)[1]
    assert after.count('<th scope="row">') == 4


def test_both_reports_appear_when_the_edition_obliges_both(en_catalog):
    """The INT edition, which is where a shared renderer could most easily print one section twice
    or drop the other."""
    proj = acr_export_preview.project(
        {"report_title": "x", "vpat_edition": acr_catalog.EDITION_INT},
        acr_catalog.build_matrix("rep-int", acr_catalog.EDITION_INT))
    html = acr_export_preview.to_html(proj)
    assert html.count("<h2>Revised Section 508 Report</h2>") == 1
    assert html.count("<h2>EN 301 549 Report</h2>") == 1
    # The template's wording on both standards at once. This fixture's EN catalog holds clauses
    # 9, 11 and 12 only; the per-edition clause 10 spelling is pinned against the full catalog in
    # test_acr_vpat_division_headings.py.
    assert "Chapter 4: Hardware" in html
    assert "Clause 9: Web (see WCAG 2.x section)" in html
    assert "Clause 12: Documentation and Support Services" in html


# ── the Word export, and the gate PRD §16 turns on ────────────────────────────────────────────

def test_the_word_document_carries_the_clauses_as_headings(projection, tmp_path):
    pytest.importorskip("docx")
    import acr_export_docx
    import docx

    path = tmp_path / "acr.docx"
    path.write_bytes(acr_export_docx.render(projection))
    document = docx.Document(str(path))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "EN 301 549 Report" in headings
    assert "Clause 9: Web (see WCAG 2.x section)" in headings
    assert "Clause 12: Documentation and Support Services" in headings


def test_the_eu_word_document_passes_acps_own_analyser(projection):
    """The same gate the 508 document goes through, over an EU one. Three more tables and four
    more headings are three more chances to emit something the analyser fails on."""
    pytest.importorskip("docx")
    import acr_export_docx

    verdict = acr_export_docx.check(acr_export_docx.render(projection))
    assert verdict["ok"] is True, verdict["failures"]
