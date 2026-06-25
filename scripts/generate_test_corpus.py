#!/usr/bin/env python3
"""Generate synthetic test corpus documents for ACP scanner regression tests.

Run once after checking out the repo, or whenever the test corpus needs to be
extended.  The output files are committed; this script documents HOW they were
built so their exact rule-trigger conditions are reproducible.

Usage:
    python scripts/generate_test_corpus.py
"""
from __future__ import annotations
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "test-corpus/files"
CORPUS.mkdir(parents=True, exist_ok=True)

# ── HTML ────────────────────────────────────────────────────────────────────
# The HTML engine is pure-Python (lxml), so these are trivially verifiable.

(CORPUS / "html-missing-title.html").write_text(
    "<!DOCTYPE html>\n"
    "<html lang=\"en\">\n"
    "<head><meta charset=\"utf-8\"></head>\n"   # no <title> → HTML_MISSING_TITLE
    "<body>\n"
    "  <h1>Page without a title</h1>\n"
    "  <p>This document intentionally omits the &lt;title&gt; element.</p>\n"
    "  <a href=\"/about\">About our organisation</a>\n"
    "</body>\n"
    "</html>\n"
)

(CORPUS / "html-heading-skip.html").write_text(
    "<!DOCTYPE html>\n"
    "<html lang=\"en\">\n"
    "<head><meta charset=\"utf-8\"><title>Heading Skip Test</title></head>\n"
    "<body>\n"
    "  <h1>Introduction</h1>\n"
    "  <h3>Sub-section</h3>\n"  # skips h2 → HTML_HEADING_SKIP
    "  <p>Heading level jumps from h1 to h3.</p>\n"
    "</body>\n"
    "</html>\n"
)

(CORPUS / "html-all-violations.html").write_text(
    "<!DOCTYPE html>\n"
    "<html>\n"                                  # no lang → HTML_MISSING_LANG
    "<head><meta charset=\"utf-8\"></head>\n"   # no <title> → HTML_MISSING_TITLE
    "<body>\n"
    "  <h1>Main section</h1>\n"
    "  <h3>Sub-section</h3>\n"                 # h1→h3 → HTML_HEADING_SKIP
    "  <img src=\"logo.png\">\n"               # no alt → HTML_IMG_MISSING_ALT
    "  <a href=\"/x\"></a>\n"                  # empty  → HTML_EMPTY_LINK
    "  <a href=\"/y\">click here</a>\n"        # vague  → HTML_VAGUE_LINK
    "  <form>\n"
    "    <input type=\"text\" id=\"name\">\n"  # no label → HTML_INPUT_NO_LABEL
    "  </form>\n"
    "</body>\n"
    "</html>\n"
)

print("HTML files written.")

# ── XLSX ─────────────────────────────────────────────────────────────────────
# Targets: XLSX-SHEET-001, XLSX-MERGE-001, XLSX-HIDDEN-001,
#          XLSX-TITLE-001, XLSX-LANG-001, XLSX-TABLE-001

from openpyxl import Workbook
from openpyxl.worksheet.table import Table

wb = Workbook()
ws = wb.active
ws.title = "Sheet1"                        # matches ^Sheet\d+$ → XLSX-SHEET-001

# Seed data in A1:C10 (used by the no-header table below)
for r in range(1, 11):
    for c in range(1, 4):
        ws.cell(row=r, column=c, value=f"R{r}C{c}")

# >20 merged cell ranges in rows 12-34 → XLSX-MERGE-001 (threshold is >20)
for i in range(23):
    row = 12 + i
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    ws.cell(row=row, column=1, value=f"Merged {i + 1}")

# Hidden row 11 with numeric content → XLSX-HIDDEN-001
# Use a numeric value: the .NET HiddenContentRule reads cell.CellValue.Text which works
# for numeric cells (<v>12345</v>) but NOT for openpyxl inline strings (<is><t>...</t></is>).
ws.cell(row=11, column=1, value=99999)
ws.cell(row=11, column=2, value=88888)
ws.row_dimensions[11].hidden = True

# Excel Table with no header row (headerRowCount=0) → XLSX-TABLE-001
tab = Table(displayName="NoHeaderTable", ref="A1:C10")
tab.headerRowCount = 0
ws.add_table(tab)

# Leave document title and language unset → XLSX-TITLE-001, XLSX-LANG-001
# (defaults are None/empty — rule checks IsNullOrWhiteSpace)

wb.save(CORPUS / "xlsx-synthetic-violations.xlsx")
print("XLSX file written.")

# ── PPTX ─────────────────────────────────────────────────────────────────────

from pptx import Presentation
from pptx.util import Inches
from pptx.oxml.ns import qn
from lxml import etree

# ── pptx-vague-links.pptx ───────────────────────────────────────────────────
# Targets: PPTX-LINK-001 (vague hyperlink text), PPTX-LANG-001 (no language)
# Avoids: PPTX-TITLE-001 (slide has a titled layout + title is filled)

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[1])   # Title and Content
slide.shapes.title.text = "Accessibility Compliance Guide"

txBox = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(5), Inches(1))
tf = txBox.text_frame
p  = tf.paragraphs[0]
run = p.add_run()
run.text = "click here"                              # vague text → PPTX-LINK-001

# Attach an external hyperlink relationship to the slide part
rel_id = slide.part.relate_to(
    "https://example.com",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    is_external=True,
)

# Embed hlinkClick inside <a:rPr> of the run
rPr = run._r.get_or_add_rPr()
hlink = etree.SubElement(rPr, qn("a:hlinkClick"))
hlink.set(qn("r:id"), rel_id)

# Do NOT set prs.core_properties.language → PPTX-LANG-001

prs.save(CORPUS / "pptx-vague-links.pptx")
print("PPTX vague-links written.")

# ── pptx-reading-order.pptx ─────────────────────────────────────────────────
# Targets: PPTX-ORDER-001 (tab order ≠ visual order), PPTX-LANG-001
# Also fires: PPTX-TITLE-001 (blank layout has no title placeholder)
#
# Strategy: add 3 shapes in REVERSE visual order.
#   Creation order  →  TabOrder  |  Y position  →  VisualRank
#   1st shape       →  0         |  y=3.5in    →  2  (bottom)
#   2nd shape       →  1         |  y=2.5in    →  1  (middle)
#   3rd shape       →  2         |  y=1.5in    →  0  (top)
# For the bottom shape: |TabOrder=0 – VisualRank=2| = 2 > 1 → fires ORDER-001

prs2 = Presentation()
slide2 = prs2.slides.add_slide(prs2.slide_layouts[6])   # blank — no title ph

for label, y_in in [("Bottom (created first)", 3.5),
                    ("Middle (created second)", 2.5),
                    ("Top (created third)", 1.5)]:
    tb = slide2.shapes.add_textbox(Inches(1), Inches(y_in), Inches(4), Inches(0.6))
    tb.text_frame.text = label

# Do NOT set language → PPTX-LANG-001

prs2.save(CORPUS / "pptx-reading-order.pptx")
print("PPTX reading-order written.")

print("\nAll synthetic corpus files generated successfully.")
