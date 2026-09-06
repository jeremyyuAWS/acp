"""Phase 6.3 — the Revised Section 508 Report, in the projection and in every export.

6.1 landed the requirements and 6.2 the matrix rows, and both were held behind a shut gate for the
same reason: a report that names Section 508 and prints none of it is the false claim #1532 found
in production. This is the slice that makes the rows printable, so it is also the slice that opens
the gate — and the assertions here are what the gate now rests on.

THE SHAPE. `criteria` stays what it was: the WCAG table's rows, in WCAG order. Section 508 rows go
under `section_508`, grouped into the chapters the standard is organised by, because that is how
ITI's 508 edition prints them and because otherwise all three renderers would have to regroup a
flat list identically. `totals` counts EVERY row, which is unchanged for a WCAG-only report and is
the only honest reading for a 508 one — a total of 55 on a 175-row report is the understatement
PRD §4.4 exists to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402
import acr_export_preview  # noqa: E402

REPORT = {"report_title": "ACP ACR", "product_name": "ACP by Movate", "product_version": "1.4.0",
          "wcag_version": "2.2", "vpat_edition": acr_catalog.EDITION_508, "vendor_name": "Movate"}


@pytest.fixture(scope="module")
def matrix_508():
    return acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)


@pytest.fixture(scope="module")
def projection(matrix_508):
    return acr_export_preview.project(REPORT, matrix_508)


# ── the projection ────────────────────────────────────────────────────────────────────────────

def test_the_wcag_table_holds_only_wcag_rows(projection):
    """A 508 requirement in the WCAG table would print with a blank Level under a Level heading —
    which reads as a missing value rather than as a category that does not apply."""
    assert len(projection["criteria"]) == 55
    assert all(r["requirement_set"] == acr_catalog.REQ_WCAG for r in projection["criteria"])
    assert all(r["level"] in ("A", "AA") for r in projection["criteria"])


def test_the_508_rows_are_grouped_into_the_regulations_own_chapters(projection):
    chapters = {c["num"]: c for c in projection["section_508"]["chapters"]}
    assert sorted(chapters) == ["3", "4", "5", "6"]
    assert {n: len(c["rows"]) for n, c in chapters.items()} == {"3": 10, "4": 69, "5": 33, "6": 8}
    assert chapters["3"]["name"] == "Functional Performance Criteria"
    assert chapters["5"]["name"] == "Software"


def test_the_totals_count_every_row_the_report_contains(projection):
    """55 WCAG + 120 Section 508. A total of 55 here would understate the document by two thirds."""
    assert projection["totals"]["total"] == 175
    assert projection["section_508"]["totals"]["total"] == 120
    assert sum(c["totals"]["total"] for c in projection["section_508"]["chapters"]) == 120


def test_the_citation_travels_with_the_rows(projection):
    """A reader has to be able to tell WHICH Section 508 — the 2017 revision, not the 1998 rule."""
    assert "36 CFR Part 1194" in projection["section_508"]["citation"]


def test_a_wcag_report_has_no_section_508_key_at_all():
    """Not an empty list: absent. A renderer that keys off presence must not print an empty
    "Revised Section 508 Report" heading for a report that never claimed one."""
    wcag = acr_export_preview.project(
        {"report_title": "W", "vpat_edition": acr_catalog.EDITION_WCAG},
        acr_catalog.build_matrix("rep-wcag"))
    assert "section_508" not in wcag
    assert wcag["totals"]["total"] == 55


def test_a_row_from_before_phase_6_is_read_as_wcag():
    """A snapshot published before the column existed carries no requirement_set. PRD §17 says a
    published report stays readable, so the projection defaults rather than dropping the row."""
    legacy = [{"criterion_num": "1.1.1", "criterion_name": "Non-text Content", "level": "A",
               "principle": "Perceivable", "final_status": "Supports", "remarks": "ok"}]
    proj = acr_export_preview.project({"report_title": "old"}, legacy)
    assert len(proj["criteria"]) == 1
    assert proj["criteria"][0]["requirement_set"] == acr_catalog.REQ_WCAG
    assert "section_508" not in proj


def test_an_internal_workflow_state_still_raises_on_a_508_row():
    """PRD §9's last line of defence applies to every row, not just the WCAG ones — the check lives
    in _conformance_cell and the 508 rows go through it too."""
    rows = [{"criterion_num": "302.1", "criterion_name": "Without Vision", "chapter": "3",
             "requirement_set": acr_catalog.REQ_SECTION_508, "final_status": "needs_review"}]
    with pytest.raises(ValueError) as e:
        acr_export_preview.project({"report_title": "x"}, rows)
    assert "302.1" in str(e.value)
    assert "internal workflow state" in str(e.value)


def test_a_chapter_the_catalog_does_not_name_still_renders_under_its_number():
    """The name is a convenience read from the catalog; the number is what the row stores. A row
    whose chapter the catalog has no name for must not vanish from the document."""
    rows = [{"criterion_num": "901.1", "criterion_name": "Invented", "chapter": "9",
             "requirement_set": acr_catalog.REQ_SECTION_508, "final_status": "Supports"}]
    proj = acr_export_preview.project({"report_title": "x"}, rows)
    assert proj["section_508"]["chapters"][0]["name"] == "Chapter 9"
    assert proj["section_508"]["chapters"][0]["rows"][0]["criterion_num"] == "901.1"


# ── the HTML rendering, which the PDF export renders from unchanged ───────────────────────────

def test_the_html_prints_the_508_report_with_its_own_tables(projection):
    html = acr_export_preview.to_html(projection)
    assert "Revised Section 508 Report" in html
    assert "36 CFR Part 1194" in html
    for caption in ("Chapter 3: Functional Performance Criteria",
                    "Chapter 4: Hardware", "Chapter 5: Software",
                    "Chapter 6: Support Documentation and Services"):
        assert caption in html, caption
    assert "302.1 Without Vision" in html
    assert "502.4 Platform Accessibility Features" in html


def test_the_508_tables_are_navigable_rather_than_one_long_grid(projection):
    """Five tables: report information, the WCAG table, and one per 508 chapter. A single 175-row
    table is technically valid and unusable with a screen reader, which is the failure mode an
    accessibility report can least afford."""
    html = acr_export_preview.to_html(projection)
    assert html.count("<caption>") == 6
    assert html.count('<th scope="col">Criteria</th>') == 5   # WCAG + four chapters


def test_the_508_tables_carry_no_level_column(projection):
    """A 508 requirement has no WCAG conformance level. An empty column under that heading reads
    as an omission; no column reads as what it is."""
    html = acr_export_preview.to_html(projection)
    after = html.split("Revised Section 508 Report", 1)[1]
    assert '<th scope="col">Level</th>' not in after
    assert after.count('<th scope="col">Conformance Level</th>') == 4


def test_every_508_row_is_a_row_header(projection):
    """`<th scope="row">` on the requirement, same as the WCAG table — the thing that makes a
    conformance cell announce which requirement it belongs to."""
    html = acr_export_preview.to_html(projection)
    after = html.split("Revised Section 508 Report", 1)[1]
    assert after.count('<th scope="row">') == 120


def test_the_undecided_cell_is_not_word_shaped_like_a_conformance_level(projection):
    """Every row of a fresh matrix is undecided, and 120 of them are about to be printed. The cell
    must be unmistakable rather than plausible — PRD §9."""
    html = acr_export_preview.to_html(projection)
    assert acr_export_preview.UNDECIDED_CELL in html
    for term in ("Supports", "Partially Supports", "Does Not Support"):
        assert f'<td>{term}</td>' not in html


# ── the Word export, and the accessibility gate PRD §16 turns on ──────────────────────────────

@pytest.fixture(scope="module")
def docx_bytes(projection):
    pytest.importorskip("docx")
    import acr_export_docx
    return acr_export_docx.render(projection)


def test_the_word_document_carries_the_508_chapters_as_headings(docx_bytes, tmp_path_factory):
    """Headings, not just tables. A screen-reader user navigates a 175-row document by heading;
    four chapters buried inside one flat run of tables is the same content and unusable."""
    import docx

    path = tmp_path_factory.mktemp("docx") / "acr.docx"
    path.write_bytes(docx_bytes)
    document = docx.Document(str(path))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "Revised Section 508 Report" in headings
    assert "Chapter 3: Functional Performance Criteria" in headings
    assert "Chapter 6: Support Documentation and Services" in headings


def test_the_508_word_tables_have_three_columns_and_a_header_row(docx_bytes, tmp_path_factory):
    import docx

    path = tmp_path_factory.mktemp("docx") / "acr.docx"
    path.write_bytes(docx_bytes)
    document = docx.Document(str(path))
    three_col = [t for t in document.tables if len(t.columns) == 3]
    assert len(three_col) == 4, "one table per reportable chapter"
    for table in three_col:
        assert [c.text for c in table.rows[0].cells] == [
            "Criteria", "Conformance Level", "Remarks and Explanations"]
    assert sum(len(t.rows) - 1 for t in three_col) == 120


def test_the_508_document_passes_acps_own_word_analyser(docx_bytes):
    """PRD §16's export gate, over the document the 508 edition actually produces.

    This is the assertion that makes the whole slice safe to ship: 120 extra rows and four extra
    tables are four more chances to emit a table with no header row or a heading level that skips,
    and the gate is what catches that. It is "no FAIL", not "all PASS" — no docx registration
    declares Coverage.FULL, so PASS is unreachable by construction, and test_acr_export_docx.py
    pins that measurement.
    """
    import acr_export_docx

    verdict = acr_export_docx.check(docx_bytes)
    assert verdict["ok"] is True, verdict["failures"]


def test_the_gate_is_not_vacuous_in_this_environment(tmp_path):
    """A checker that reports nothing on a broken file reports nothing on a good one too, and the
    test above would then be a fact about the checker rather than about the document.

    The defect is an empty heading, the nastier of the two `test_acr_export_docx.py` uses: it sits
    in the outline, breaks no level sequence, and has no runs to fail contrast on, so every other
    check ACP has passes it.

    ONE LIMIT, MEASURED RATHER THAN LEFT IMPLIED: `check()` answers ok=True for bytes that are not
    a zip at all — office_structure.docx_checks logs the BadZipFile and returns no findings, and no
    findings reads as no failures. That is pre-existing and outside this slice, so the probe here
    uses a real document with a real defect instead of garbage. It is reported rather than fixed
    quietly.
    """
    from docx import Document
    import acr_export_docx

    document = Document()
    document.add_heading("Title", level=1)
    document.add_heading("", level=2)
    document.add_paragraph("body")
    path = tmp_path / "broken.docx"
    document.save(path)

    verdict = acr_export_docx.check(path.read_bytes(), tmp_dir=tmp_path / "check")
    assert verdict["ok"] is False, "the gate did not notice a defect it claims to detect"
    assert verdict["failures"], verdict


def test_the_gate_closes_again_if_the_catalog_is_not_deployed(monkeypatch):
    """`requirement_sets_available()` asks whether the file is THERE, and this is the only test
    that reaches the answer "no".

    Written after a bite check found nothing: replacing the existence check with an unconditional
    `available.add(REQ_SECTION_508)` turned no test red, because the catalog is committed and every
    other test runs with it present. A guard whose false branch nothing exercises is a guard nobody
    knows is broken — and the false branch is the one that matters, since a deployment shipping
    without config/section-508.json would otherwise offer an edition it cannot populate.
    """
    monkeypatch.setattr(acr_catalog, "_SECTION_508_PATH",
                        Path("/nonexistent/section-508.json"))
    assert acr_catalog.requirement_sets_available() == frozenset({acr_catalog.REQ_WCAG})
    assert acr_catalog.offerable_editions() == [acr_catalog.EDITION_WCAG]
    assert acr_catalog.missing_requirement_sets(acr_catalog.EDITION_508) == frozenset(
        {acr_catalog.REQ_SECTION_508})
