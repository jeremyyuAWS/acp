"""The exported ACR PDF discloses what has NOT been validated about its own accessibility.

WHY THIS IS ITS OWN FILE AND ITS OWN CLAIM. `tests/test_acr_export_pdf.py` proves the document is
PDF/UA-1 conformant and structurally sound. That is a result about MACHINE conformance, and #1159
measured exactly how far it goes: two defects shipped through 0 veraPDF failures and a fully green
structural suite — the whole report silently set in serif, and row headers restyled into a
redesign — both found only by rendering the page and looking at it.

So an ACR PDF can be conformant, pass every assertion in this repository, and still be one no
screen-reader user has ever read. ADR 0034 names the two checks that would close that gap — PAC
2024 and an NVDA/VoiceOver pass — and neither has been run against this renderer.

The disclosure has to live INSIDE the document. A PDF travels: it goes into a customer's
procurement file and is read by people who will never see this repository, an ADR, or a pull
request. A caveat that stays on the server is one the holder of the artifact never gets, and
shipping an "accessible export" while withholding that distinction is the shape PRD §4.4 forbids —
optimising for a compliance signal instead of making the limitation visible.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pytest.importorskip("weasyprint")

import acr_export_pdf  # noqa: E402
import acr_export_preview  # noqa: E402

CRITERIA = [{"criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA",
             "principle": "Perceivable", "final_status": "Supports", "remarks": ""}]
REPORT = {"report_title": "ACP ACR", "product_name": "ACP by Movate",
          "product_version": "1.4.0"}


def _flat_text(pdf_bytes: bytes, tmp_path) -> str:
    """Extracted page text with whitespace collapsed.

    NORMALISED DELIBERATELY. pdfminer emits a newline at every line break, so a phrase that wraps
    — "screen-reader pass", "not sufficient" — is absent from the raw extraction while being
    perfectly visible to a reader. Asserting on raw text would fail for a formatting reason and
    read as a missing disclosure, which is the wrong alarm entirely.
    """
    path = tmp_path / "acr.pdf"
    path.write_bytes(pdf_bytes)
    from pdfminer.high_level import extract_text
    return re.sub(r"\s+", " ", extract_text(str(path)))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    pdf = acr_export_pdf.render(REPORT, CRITERIA)
    return _flat_text(pdf, tmp_path_factory.mktemp("acrlim"))


def test_the_pdf_names_the_checks_that_have_not_been_run(rendered):
    """The two ADR 0034 gates, by name. Naming them is what makes the disclosure actionable —
    "some checks are outstanding" tells a reader nothing they can follow up."""
    assert "PAC 2024" in rendered, rendered[:500]
    assert "screen-reader pass" in rendered, rendered[:500]


def test_the_pdf_says_automated_validation_is_not_sufficient(rendered):
    """The sentence that stops "veraPDF: 0 failures" being read as "a disabled user can use this"."""
    assert "necessary and not sufficient" in rendered, rendered[:500]
    assert "automated only" in rendered.lower(), rendered[:500]


def test_the_notice_is_on_the_first_page_above_the_conformance_table(rendered):
    """A reader who stops after page one has still seen it. Anchored after the <h1>, so the
    notice precedes the first criterion in reading order."""
    notice = rendered.find("Limitations of this document")
    first_criterion = rendered.find("1.4.3")
    assert notice != -1, rendered[:300]
    assert first_criterion != -1, rendered[:300]
    assert notice < first_criterion, "the limitations notice appears after the conformance table"


def test_the_builder_refuses_html_it_cannot_anchor_the_notice_to():
    """A silently-unmodified return would ship exactly the document this exists to prevent.

    The failure is invisible in review — the PDF is still conformant, still passes every
    structural assertion, and simply omits its own disclosure — so the builder raises instead.
    """
    with pytest.raises(ValueError, match="limitations notice"):
        acr_export_pdf.with_limitations("<html><body><p>no heading here</p></body></html>")


def test_the_screen_preview_is_left_alone():
    """The caveat is about the exported artifact travelling away from this application. The
    on-screen preview sits inside the workspace that explains itself, so it is not rewritten —
    and a change that started rewriting it would be changing a different thing."""
    projection = acr_export_preview.project(REPORT, CRITERIA)
    assert "PAC 2024" not in acr_export_preview.to_html(projection)


def test_the_notice_is_escaped_into_the_document():
    """It is inserted as HTML. An unescaped notice would be an injection point the day someone
    makes the text configurable, and the escape is cheap now rather than remembered later."""
    html = acr_export_pdf.with_limitations(
        "<html><body><h1>t</h1></body></html>", notice='a <script>alert("x")</script> & b')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
