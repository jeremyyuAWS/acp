"""The shipped conformance report is not PDF/UA-1 conformant. Pinned here, before it is fixed.

WHAT THIS FILE IS. A regression fixture that demonstrates a gap, in the same spirit as
`test_untagged_is_still_the_open_finding` did for the ReportLab renderer it replaced: the defect
is recorded as an executable fact rather than left implied by silence. It is expected to FAIL —
loudly, with the clause numbers in the message — on the day the renderer is replaced. That
failure is the signal to delete this file, not to weaken it.

WHY IT COULD NOT BE WRITTEN BEFORE. ADR 0034 and `spike/weasyprint-report/README.md` both list
"veraPDF or PAC 2024 validation" as the required automated gate and both record it as **not
runnable** — "no local Java". A JRE is present now (Java 21), so the gate that gated the whole
migration can finally be run. Everything below is a measurement taken with veraPDF 1.30.2, not a
restatement of the ADR.

WHAT IT MEASURED. `report_tagged.build_tagged_report` — the renderer serving
`/scans/{sid}/report.pdf` today — produces a document that fails PDF/UA-1 on two rules:

    clause 7.1 test 8   x1   the catalog has no XMP metadata stream. Chromium writes none, and
                             PDF/UA requires one (it carries the UA identifier).
    clause 7.1 test 3   x7   content neither marked as Artifact nor tagged as real content.

The second is worth reading twice. Chromium draws its own print header and footer outside the
structure tree, so seven content items are orphaned — and the footer it draws is the local
temp path the HTML was written to:

    file:///tmp/acp_report_<random>/report.html

That path is printed on every page of a document ACP hands a customer as audit evidence. The
renderer passes `--print-to-pdf-no-header`, and in this Chromium build it does not suppress it.
Both facts are visible in the rendered page, not just in the tag tree.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM. That the Chromium renderer is bad work: it produces a
real structure tree with a correct heading outline, 9 TH cells and 27 TD cells, and it closed the
CRITICAL `pdf.tagged` finding the ReportLab path could not. It is better than what preceded it. It
is simply not PDF/UA-1, which is the standard a conformance report handed to an accessibility
auditor should meet.

THE GATE IS PROVEN NON-VACUOUS, twice, because "veraPDF says PASS" is worth exactly as much as
the check behind it: a known-untagged corpus PDF must FAIL, and a known-good tagged PDF must
PASS. Without both, a validator that had silently stopped validating would look like good news.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from verapdf import NO_VERAPDF, VERAPDF_OK, validate  # noqa: E402

_CHROMIUM = Path(os.environ.get(
    "ACP_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
_NO_CHROMIUM = f"Chromium not found at {_CHROMIUM}"

pytestmark = pytest.mark.skipif(not VERAPDF_OK, reason=NO_VERAPDF)

# The two rules the shipped renderer fails. Named individually rather than counted, because
# "2 failures" would still pass if one were fixed and a different one appeared.
_XMP_METADATA = "7.1-8"
_ORPHAN_CONTENT = "7.1-3"

_FILES = [
    {"file": "a.pdf", "status": "done", "compliant": 1, "score": 90,
     "skipped_rules": 0, "issues": []},
    {"file": "b.docx", "status": "done", "compliant": 0, "score": 55, "skipped_rules": 0,
     "issues": [{"wcag": "SC_1_1_1", "severity": "CRITICAL"},
                {"wcag": "SC_2_4_2", "severity": "SERIOUS"}]},
    {"file": "c.xlsx", "status": "done", "compliant": 0, "score": 71, "skipped_rules": 2,
     "issues": [{"wcag": "SC_1_4_3", "severity": "MODERATE"}]},
]
_RUN = {"id": "selfcheck", "completed_at": "2026-08-04T00:00:00", "avg_score": 72,
        "files": 3, "certifiable": 1, "uncertain": 0, "error": 0}
_META = {"target": "WCAG 2.1 Level AA", "version": "3", "hash": "abc"}


@pytest.fixture(scope="module")
def shipped_report(tmp_path_factory) -> Path:
    """A report through the REAL shipped entry point — not a hand-rolled document, or this
    would pin a fixture rather than the renderer customers actually receive."""
    # This fixture pins the renderer customers receive in the Linux container. Desktop Chrome
    # on macOS writes the PDF and then keeps its browser process alive past the renderer's
    # timeout, which is a different execution environment and cannot measure this production
    # regression. The candidate WeasyPrint report remains fully validated on every platform.
    if sys.platform != "linux":
        pytest.skip("shipped Chromium regression is measured in its Linux production runtime")
    if not _CHROMIUM.exists():
        pytest.skip(_NO_CHROMIUM)
    import report_tagged
    out = tmp_path_factory.mktemp("shipped") / "report.pdf"
    out.write_bytes(report_tagged.build_tagged_report(_RUN, _FILES, _META))
    return out


# ── the gate itself must be capable of failing, and of passing ───────────────────────────────

def test_verapdf_fails_a_known_untagged_pdf():
    """An untagged PDF from the ground-truth corpus. If this passes, the validator is not
    validating and every other result in this file is worthless."""
    corpus = ACP / "test-corpus/oracle/pdf-untagged.pdf"
    if not corpus.exists():
        pytest.skip(f"corpus fixture missing: {corpus}")
    result = validate(corpus)
    assert not result.compliant, (
        "veraPDF called an untagged PDF PDF/UA-1 conformant — the gate is not working")


def test_verapdf_passes_a_known_good_tagged_pdf(tmp_path):
    """The other direction, so a validator that failed EVERYTHING would not look like a finding
    about our renderer. Built with WeasyPrint's pdf/ua-1 variant from minimal semantic HTML."""
    weasyprint = pytest.importorskip("weasyprint")
    html = ("<!DOCTYPE html><html lang='en'><head><title>Known good</title></head>"
            "<body><h1>Known good</h1><p>A conformant document.</p></body></html>")
    good = tmp_path / "good.pdf"
    weasyprint.HTML(string=html).write_pdf(good, pdf_variant="pdf/ua-1")
    result = validate(good)
    assert result.compliant, f"the control document did not pass: {result.summary()}"


# ── the gap ──────────────────────────────────────────────────────────────────────────────────

def test_the_shipped_renderer_is_not_pdfua_conformant(shipped_report):
    """THE regression fixture. Delete this file when the renderer is replaced — do not relax it.

    A conformance report is audit evidence. The auditor most likely to open it is the one most
    likely to run a checker over it, and this is what that checker says today.
    """
    result = validate(shipped_report)
    assert not result.compliant, (
        "the shipped renderer now PASSES PDF/UA-1 — if that is intended, this whole file is "
        f"obsolete and should be deleted along with the gap it pinned. {result.summary()}")


def test_the_failure_is_missing_xmp_metadata(shipped_report):
    """Chromium writes no XMP metadata stream. PDF/UA requires one — it carries the UA
    identifier a consumer reads to know what profile the file claims."""
    result = validate(shipped_report)
    assert _XMP_METADATA in result.failure_keys, (
        f"expected a clause {_XMP_METADATA} (metadata) failure; got {result.summary()}")


def test_the_failure_includes_untagged_orphan_content(shipped_report):
    """Content that is neither Artifact nor tagged. PDF/UA forbids it: a screen reader is given
    real page content with no way to reach it and no indication it is decorative.

    This is Chromium's own print furniture — the same furniture that stamps the local temp path
    onto every page (see test_the_report_leaks_a_local_temp_path_onto_every_page).
    """
    result = validate(shipped_report)
    assert _ORPHAN_CONTENT in result.failure_keys, (
        f"expected a clause {_ORPHAN_CONTENT} (orphan content) failure; got {result.summary()}")


def test_the_report_leaks_a_local_temp_path_onto_every_page(shipped_report):
    """A separate defect from the tagging one, found while measuring it, and the more
    embarrassing of the two: the PDF handed to a customer's auditor carries the server-side
    temporary directory the HTML was rendered from.

    Asserted on extracted page text rather than on the raw bytes, so it is a statement about
    what a reader SEES rather than about an incidental string in an object stream.
    """
    pdfium = pytest.importorskip("pypdfium2")
    doc = pdfium.PdfDocument(str(shipped_report))
    try:
        pages_with_path = [
            i + 1 for i in range(len(doc))
            if "file:///" in doc[i].get_textpage().get_text_range()
        ]
        page_count = len(doc)
    finally:
        doc.close()
    assert pages_with_path, (
        "no page carries a file:/// path any more — if the print furniture was fixed, delete "
        "this test with the rest of the file")
    assert len(pages_with_path) == page_count, (
        f"expected the leak on every page; found it on {pages_with_path} of {page_count}")
