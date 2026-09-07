"""The Section 508 and EN 301 549 sub-headings, worded the way the ITI template words them.

#1648 laid the WCAG section out as the template does. It left the 508 chapters and EN clauses
headed with ACP's own catalog names — `Chapter 3: Functional Performance Criteria` where the
template writes `… (FPC)`, `Clause 9: Web` where it writes `Clause 9: Web (see WCAG 2.x
section)`. The template's text was already in `config/vpat-2.5rev.json`; this is the wiring.

Two things the wiring must not do, and both are pinned here: it must not change `name` (the
catalog's data about the standard — a heading is data about the document), and it must not be the
reason a division fails to print. A lookup that comes back empty prints what always printed.
"""
import io

import pytest

import acr_catalog
import acr_export_preview


def _projection(edition, rows=None):
    rows = rows if rows is not None else acr_catalog.build_matrix("r-1", edition)
    return acr_export_preview.project({"vpat_edition": edition, "report_title": "ACP"}, rows)


def _headings(projection, key):
    return [ch["heading"] for ch in projection[key]["chapters"]]


# ── the template's wording, per edition ───────────────────────────────────────────────────────

def test_the_508_chapters_carry_the_templates_wording():
    assert _headings(_projection(acr_catalog.EDITION_508), "section_508") == [
        "Chapter 3: Functional Performance Criteria (FPC)",
        "Chapter 4: Hardware",
        "Chapter 5: Software",
        "Chapter 6: Support Documentation and Services",
    ]


def test_the_en_clauses_carry_the_templates_wording():
    headings = _headings(_projection(acr_catalog.EDITION_EU), "en_301_549")
    assert headings[0] == "Clause 4: Functional Performance Statements (FPS)"
    assert "Clause 9: Web (see WCAG 2.x section)" in headings
    assert headings[-1] == "Clause 13: ICT Providing Relay or Emergency Service Access"
    assert len(headings) == 10


def test_clause_10_is_worded_per_edition_not_per_standard():
    """The template disagrees with itself, and the document follows the template a reader holds.

    EU writes `Non-web Documents`, INT writes `Non-Web Documents`. The catalog captured that
    deliberately (#1645); normalising it in the projection would undo the capture and print an
    INT report that matches neither edition exactly.
    """
    eu = _headings(_projection(acr_catalog.EDITION_EU), "en_301_549")
    int_ = _headings(_projection(acr_catalog.EDITION_INT), "en_301_549")
    assert "Clause 10: Non-web Documents" in eu
    assert "Clause 10: Non-Web Documents" in int_


def test_the_int_edition_words_both_standards():
    projection = _projection(acr_catalog.EDITION_INT)
    assert _headings(projection, "section_508")[0] == (
        "Chapter 3: Functional Performance Criteria (FPC)")
    assert _headings(projection, "en_301_549")[0] == (
        "Clause 4: Functional Performance Statements (FPS)")


# ── what the wiring must not change ───────────────────────────────────────────────────────────

def test_name_stays_the_catalogs_while_heading_becomes_the_templates():
    """Two fields on purpose. `name` is what the standard calls the division; `heading` is what
    the document prints. The 508 test that asserts `name == "Functional Performance Criteria"`
    is about the catalog and must not break because the template abbreviates."""
    chapter = _projection(acr_catalog.EDITION_508)["section_508"]["chapters"][0]
    assert chapter["name"] == "Functional Performance Criteria"
    assert chapter["heading"] == "Chapter 3: Functional Performance Criteria (FPC)"
    # And where the two genuinely disagree, both are kept rather than one overwriting the other.
    clause_4 = _projection(acr_catalog.EDITION_EU)["en_301_549"]["chapters"][0]
    assert clause_4["name"] == "Principles"
    assert clause_4["heading"] == "Clause 4: Functional Performance Statements (FPS)"


def test_no_edition_means_the_headings_every_renderer_printed_before():
    """The fallback is the old behaviour, exactly. A report with no edition selected is not a new
    kind of report; it is the report as it rendered before the template's text existed as data."""
    rows = acr_catalog.build_matrix("r-1", acr_catalog.EDITION_INT)
    projection = acr_export_preview.project({"report_title": "ACP"}, rows)
    assert _headings(projection, "section_508")[0] == "Chapter 3: Functional Performance Criteria"
    assert _headings(projection, "en_301_549")[0] == "Clause 4: Principles"


def test_a_division_the_template_does_not_list_still_prints():
    """The template covers chapters 3-6. A row filed under a chapter it does not know must render
    under its number rather than vanish — a heading lookup is never a reason to drop a row."""
    rows = acr_catalog.build_matrix("r-1", acr_catalog.EDITION_508)
    stray = dict(next(r for r in rows if r.get("requirement_set") == acr_catalog.REQ_SECTION_508))
    stray.update(criterion_num="9.1", criterion_name="Stray", chapter="9")
    projection = _projection(acr_catalog.EDITION_508, rows + [stray])
    chapters = {ch["num"]: ch for ch in projection["section_508"]["chapters"]}
    assert "9" in chapters
    assert chapters["9"]["rows"][0]["criterion_num"] == "9.1"
    # Neither the catalog nor the template names it, so its heading is its number — once.
    assert chapters["9"]["heading"] == "Chapter 9"


def test_every_division_row_still_prints_exactly_once():
    projection = _projection(acr_catalog.EDITION_INT)
    for key, expected in (("section_508", 120), ("en_301_549", 314)):
        nums = [r["criterion_num"] for ch in projection[key]["chapters"] for r in ch["rows"]]
        assert len(nums) == len(set(nums)) == expected, key


# ── the rendered formats ──────────────────────────────────────────────────────────────────────

def test_the_html_captions_print_the_templates_wording():
    html = acr_export_preview.to_html(_projection(acr_catalog.EDITION_INT))
    assert "<caption>Chapter 3: Functional Performance Criteria (FPC) — " in html
    assert "<caption>Clause 9: Web (see WCAG 2.x section) — " in html
    assert "<caption>Clause 10: Non-Web Documents — " in html
    # And not the old shape, which would mean a renderer rebuilt the heading itself.
    assert "<caption>Chapter 3: Functional Performance Criteria — " not in html


def test_the_word_headings_print_the_templates_wording():
    pytest.importorskip("docx")
    import docx

    import acr_export_docx

    document = docx.Document(io.BytesIO(
        acr_export_docx.render(_projection(acr_catalog.EDITION_INT))))
    headings = [p.text for p in document.paragraphs if p.style.name == "Heading 3"]
    assert "Chapter 3: Functional Performance Criteria (FPC)" in headings
    assert "Clause 9: Web (see WCAG 2.x section)" in headings
    assert "Clause 10: Non-Web Documents" in headings
    assert "Chapter 3: Functional Performance Criteria" not in headings


def test_the_word_document_still_passes_the_accessibility_gate():
    """Row 14's gate, over the largest document ACP produces: 489 rows under 17 level-3
    headings. Changing heading text cannot break heading structure, but a test that says so is
    cheaper than a customer finding out."""
    pytest.importorskip("docx")
    import acr_export_docx

    verdict = acr_export_docx.check(acr_export_docx.render(_projection(acr_catalog.EDITION_INT)))
    assert verdict["ok"] is True, verdict["failures"]


def test_no_heading_uses_the_mark():
    """ADR 0053's Q1 is open. The template's own sub-headings do not contain the word VPAT, and
    nothing on the way from catalog to document may add it."""
    projection = _projection(acr_catalog.EDITION_INT)
    for key in ("section_508", "en_301_549"):
        for heading in _headings(projection, key):
            assert "VPAT" not in heading and "®" not in heading, heading
