"""The ACR as a PDF/UA-1 tagged PDF (PRD §16) — the accessible export.

WHAT THIS IS AND IS NOT. It renders the SAME projection `acr_export_preview` already builds, so
the PDF and the on-screen preview cannot disagree about a conformance level. It is **not** the
official ITI VPAT® document — that template is Phase 5 and gated on a licensing decision — and the
PDF says so on its own first page, because a PDF travels: it is mailed, filed and read far from
the application that produced it, and a disclaimer only shown in the UI is a disclaimer the reader
of the artifact never sees.

WHY WEASYPRINT AND NOT THE SHIPPED RENDERER. `api/report.py::_tag_pdf` fabricates an empty
`/StructTreeRoot` that satisfies ACP's own `pdf.tagged` rule while giving a screen-reader user
nothing — ADR 0034 rules that out. The Chromium path leaks the local temp path into a footer on
every page and fails veraPDF on 8 checks. `report_weasy` (#1159) produces a real structure tree
and passes veraPDF ua1 with 0 failures, so this reuses that proven approach rather than inventing
a third.

TWO GATES BEHIND THIS ARE STILL UNRUN, and that is recorded here rather than only in a PR
description. ADR 0034 conditions the renderer migration on **PAC 2024** (Windows-only) and a
**screen-reader pass** (NVDA/VoiceOver); neither has been run for this renderer, and #1159 carries
`hold-for-review` for exactly that reason. veraPDF passing is necessary and NOT sufficient: #1159
documents two defects that shipped through 0 veraPDF failures and a green structural suite — the
whole report silently set in serif, and row headers restyled into a redesign — both found only by
rendering the page and looking at it. So what this module can honestly claim is: a real structure
tree, the structural properties asserted in tests, and PDF/UA-1 conformance per veraPDF. What it
cannot yet claim is that a screen-reader user has read one successfully.

FONT STACK IS LITERAL, DELIBERATELY. #1159's first version interpolated it through an autoescaping
Jinja environment and shipped `font-family: &#34;Liberation Sans&#34;` — invalid CSS, silently
dropped, every page set in WeasyPrint's default serif. The tests here assert the EMBEDDED FONT of
the built PDF rather than the CSS string, because asserting the string would have passed the whole
time that bug was live.
"""
from __future__ import annotations

import html as _html

import acr_export_preview

# Metric-compatible with Arial, present on the runners, and named literally — never interpolated.
FONT_STACK = '"Liberation Sans", "DejaVu Sans", Arial, sans-serif'

# What a reader must be told about this artifact, inside the artifact.
LIMITATIONS = (
    "This document was produced by ACP's accessible-PDF renderer. It is validated as PDF/UA-1 by "
    "veraPDF and its structure tree is asserted by automated tests. Two checks that ADR 0034 "
    "requires before this renderer replaces the previous one have NOT been run against it: a PAC "
    "2024 pass and a screen-reader pass (NVDA/VoiceOver). Automated validation is necessary and "
    "not sufficient — it cannot tell you that a screen-reader user read this successfully."
)

_PDF_CSS = f"""
@page {{
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-center {{
    content: "Page " counter(page) " of " counter(pages);
    font: 9pt {FONT_STACK};
    color: #595959;
  }}
}}
html {{ font-family: {FONT_STACK}; }}
body {{ font: 10pt/1.45 {FONT_STACK}; color: #1a1a1a; background: #fff; margin: 0; }}
h1 {{ font-size: 18pt; margin: 0 0 .4em; }}
h2 {{ font-size: 13pt; margin: 1.2em 0 .4em; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.2em; }}
th, td {{ border: 0.5pt solid #767676; padding: 4pt 5pt; text-align: left; vertical-align: top; }}
/* Scoped to column headers ONLY. #1159 found that a bare `th` rule also restyled row headers —
   bold, shaded, heavier-ruled — redesigning two tables. ISO 14289 wants the cell TAGGED as a
   header and says nothing about its weight. */
th[scope="col"] {{ background: #f0f0f0; font-weight: 700; }}
caption {{ text-align: left; font-weight: 700; padding-bottom: 4pt; }}
.notice {{ border: 1pt solid #767676; padding: 6pt 8pt; margin-bottom: 10pt; }}
.draft, .stale {{ font-size: 8.5pt; color: #595959; }}
thead {{ display: table-header-group; }}   /* repeat headers across page breaks */
tr {{ page-break-inside: avoid; }}
"""


def render_pdf_html(projection: dict) -> str:
    """The print-tuned HTML for the PDF.

    Built from `acr_export_preview.to_html` rather than a second template: two templates drift,
    and the drift shows up as the PDF and the screen stating different conformance levels for the
    same criterion — the one disagreement this feature must never produce. Only the STYLESHEET is
    replaced (screen CSS for print CSS) plus the limitations notice; every fact, every cell and
    every disclaimer comes from the shared projection.
    """
    base = acr_export_preview.to_html(projection)

    # Swap the screen stylesheet for the print one. Anchored on the literal <style> block the
    # preview emits; if that ever stops matching, the assertion below fails loudly rather than
    # silently shipping a PDF with no styles at all.
    start, end = base.index("<style>"), base.index("</style>") + len("</style>")
    styled = base[:start] + f"<style>{_PDF_CSS}</style>" + base[end:]
    if "Liberation Sans" not in styled:
        raise RuntimeError("the print stylesheet did not reach the document — refusing to build a "
                           "PDF whose font stack silently fell back (see the module docstring)")

    # The limitations notice goes immediately after the <h1>, so it is on page 1 above the table.
    marker = "</h1>"
    idx = styled.index(marker) + len(marker)
    notice = (f'\n<p class="notice"><strong>Limitations of this document.</strong> '
              f'{_html.escape(LIMITATIONS)}</p>')
    return styled[:idx] + notice + styled[idx:]


def build_acr_pdf(projection: dict) -> bytes:
    """Render the ACR projection as a PDF/UA-1 tagged PDF.

    `pdf_variant="pdf/ua-1"` is what makes WeasyPrint emit the structure tree, the XMP identifier
    and the document-level entries the profile requires. WeasyPrint's own documentation is explicit
    that selecting the variant does not GUARANTEE a conformant document, which is why this ships
    behind a veraPDF gate in CI rather than behind a claim.
    """
    import weasyprint

    return weasyprint.HTML(string=render_pdf_html(projection)).write_pdf(pdf_variant="pdf/ua-1")


def filename_for(report: dict) -> str:
    """A download filename that identifies what the reader is holding.

    Includes the product version and revision because an ACR is a statement about ONE version;
    two files called `acr.pdf` on a reviewer's desktop is how the wrong one gets sent.
    """
    parts = [str(report.get("product_name") or "ACP"), str(report.get("product_version") or ""),
             f"rev{report.get('revision') or 1}"]
    slug = "-".join(p.strip().replace(" ", "-") for p in parts if str(p).strip())
    safe = "".join(ch for ch in slug if ch.isalnum() or ch in "-_.")
    return f"{safe or 'acr'}-accessibility-conformance-report.pdf"
