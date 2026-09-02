"""The ACR export as a PDF a screen-reader user can actually read (PRD §16, ADR 0034).

WHAT THIS RENDERS, AND WHAT IT DELIBERATELY DOES NOT DECIDE
-----------------------------------------------------------
Nothing. It renders `acr_export_preview.to_html()` — the SAME html the `/preview?format=html`
screen serves — and adds print CSS. Every honesty constraint in this export therefore lives
exactly once, in acr_export_preview: no workflow state in the conformance column, no draft status
presented as a decision, no criterion omitted for being inconvenient. A PDF that built its own
table from the projection could drift from the preview a reviewer approved, and the drift would
be invisible: two documents, one claim, and no test that compares them.

The stylesheet added below is additive and touches PAGINATION ONLY — page size, margins, running
table headers, avoiding a row split across a page break. It cannot add, remove or relabel a cell,
which is what makes "the PDF and the preview cannot disagree" a structural property rather than a
promise.

`pdf_variant="pdf/ua-1"` IS THE WHOLE THING, so it is asserted rather than assumed
-----------------------------------------------------------------------------------
Measured on this repo's own export, 55 criteria and 61 rows, with veraPDF 1.30.2:

    write_pdf()                        → NOT conformant, 987 failed checks
                                         (clause 6.2 t1, 7.1 t3, t8, t10, t11)
    write_pdf(pdf_variant="pdf/ua-1")  → PDF/UA-1 conformant, 0 failed checks

The flag is what emits the structure tree, the XMP metadata stream, /MarkInfo and the viewer
preference that makes a reader announce the document's title instead of its filename. Drop it and
the output still opens, still looks right, still prints — and is no longer a tagged PDF. That is
the failure mode this module is most exposed to, so `test_acr_export_pdf.py` pins the marker
objects directly and does not rely on veraPDF being installed to catch it.

FAIL CLOSED ON A MISSING RENDERER. `render()` raises rather than returning an untagged PDF from
some fallback. An ACR is a conformance claim that goes to a customer's procurement file; shipping
one that quietly lost its structure tree because a dependency was absent is worse than serving an
error that names the dependency. The route turns this into a 503 that says what is missing.
"""
from __future__ import annotations

import acr_export_preview

# Pagination only. Deliberately no colour, no font stack, no spacing that changes what a cell
# says — see the module docstring. `thead` repeating is the accessibility-relevant one: a 55-row
# conformance table crossing six pages with its header row on page one only forces a reader to
# hold four column meanings in their head for five pages.
PRINT_CSS = """
@page { size: A4; margin: 18mm 14mm; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
table { break-inside: auto; }
h1 { break-after: avoid; }
caption { break-after: avoid; }
"""

# The PDF/UA-1 variant. Named rather than inlined at the call site so the test that pins it and
# the code that uses it cannot drift apart.
PDF_VARIANT = "pdf/ua-1"

MISSING_RENDERER = (
    "the PDF renderer is unavailable — WeasyPrint is not importable in this deployment, so the "
    "accessible ACR export cannot be produced. Install `weasyprint` (api/requirements.txt) and "
    "the Pango/Cairo system libraries the image provides; the JSON and HTML previews are "
    "unaffected."
)


class RendererUnavailable(RuntimeError):
    """Raised when WeasyPrint cannot be imported. Never a fallback to an untagged PDF."""


def is_available() -> bool:
    """True when a tagged PDF can actually be produced here.

    Import-only, like ocr.is_available(): callers need to know whether the lane runs before they
    offer a download, and finding out by rendering a whole report to discover the answer is not a
    check, it is the work.
    """
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


def render_html(html: str) -> bytes:
    """One accessible PDF from already-rendered export HTML.

    Separate from `render()` so a test can hand it a known-untagged page and prove the validator
    and the structural assertions are non-vacuous — a check that only ever sees conformant input
    cannot distinguish "this is tagged" from "this assertion is broken".
    """
    try:
        import weasyprint
    except Exception as exc:                                # pragma: no cover - env-dependent
        raise RendererUnavailable(MISSING_RENDERER) from exc

    return weasyprint.HTML(string=html).write_pdf(
        stylesheets=[weasyprint.CSS(string=PRINT_CSS)], pdf_variant=PDF_VARIANT)


def render(report: dict, criteria: list[dict], *, evidence_by_criterion=None,
           stale_ids=None) -> bytes:
    """The report's accessible PDF, built from the same projection the preview screens use."""
    projection = acr_export_preview.project(
        report, criteria, evidence_by_criterion=evidence_by_criterion, stale_ids=stale_ids)
    return render_html(acr_export_preview.to_html(projection))


def filename_for(report: dict) -> str:
    """A download name a person can find again in their Downloads folder.

    The report id is in it because a procurement file collects several of these and
    "conformance-report.pdf" three times is how the wrong one gets attached to a bid.

    BOTH KEYS, because the id has two names depending on where the dict came from. The store row
    is `SELECT * FROM acr_report`, whose primary key column is `id`; the API surface and
    `acr_export_preview`'s projection call it `report_id`. Reading only the latter is what the
    end-to-end test caught: the route passes the raw store row, `report_id` was absent, and every
    report in the system downloaded as the same `acr-report.pdf` — the exact collision this
    function exists to prevent, produced by the function itself.
    """
    rid = str(report.get("id") or report.get("report_id") or "report").strip() or "report"
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in rid)
    rev = report.get("revision")
    suffix = f"-rev{rev}" if rev else ""
    return f"acr-{safe}{suffix}.pdf"
