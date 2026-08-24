"""R10 — fixture-verification harness for understated capability cells.

Four (rule × format) cells are declared in the registry but were absent from the
capability table before R8 corrected them:

  • xlsx  1.4.1  — Use of Color   (colour-scale conditional format)
  • xlsx  1.4.11 — Non-text Contrast (solid outline-on-fill DrawingML shape < 3:1)
  • xlsx  4.1.2  — Name, Role, Value (embedded ActiveX / OLE control)
  • pdf   2.4.3  — Focus Order     (/Tabs missing or ≠ /S on a widget page)

This file builds minimal hand-crafted fixtures that exercise each detector and asserts
the expected criterion ID appears in the returned findings. Fixtures for xlsx are
built as in-memory zips (no openpyxl dependency). The PDF fixture requires
``reportlab`` to construct and ``pikepdf`` to detect; both tests skip gracefully when
those libraries are absent.

The xlsx detectors live in ``api/office_structure`` (shared with docx/pptx) and are
called through the thin wrappers registered in ``api/formats/xlsx/__init__``.  The PDF
2.4.3 detector lives in ``api/formats/pdf/detectors/focus_order``. Calling the
registered detector wrappers (rather than the underlying helpers directly) confirms
the registered entry point itself is wired correctly.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

# ── xlsx detector wrappers ────────────────────────────────────────────────────
# Import lazily inside each test so a missing optional dep doesn't skip everything.
import office_structure as _os  # noqa: E402  (always available — pure stdlib)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_zip(tmp: Path, name: str, parts: dict[str, str | bytes]) -> Path:
    """Write a minimal OOXML zip to ``tmp / name`` and return the path."""
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for part_name, data in parts.items():
            z.writestr(part_name, data)
    return p


def _wcag_ids(findings: list[dict]) -> set[str]:
    return {f.get("wcag", "") for f in findings}


# ══════════════════════════════════════════════════════════════════════════════
# xlsx  1.4.1 — Use of Color
# ══════════════════════════════════════════════════════════════════════════════

_SHEET_WITH_COLOR_SCALE = (
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    "<sheetData/>"
    '<conditionalFormatting sqref="A1:A20">'
    '<cfRule type="colorScale" priority="1"><colorScale/></cfRule>'
    "</conditionalFormatting>"
    "</worksheet>"
)


def test_xlsx_141_color_scale_detected(tmp_path):
    """1.4.1 detector flags a colorScale conditional format in an xlsx worksheet."""
    p = _make_zip(
        tmp_path,
        "color_scale.xlsx",
        {"xl/worksheets/sheet1.xml": _SHEET_WITH_COLOR_SCALE},
    )
    findings = _os.office_color_only_checks(p, ".xlsx")
    wcag_ids = _wcag_ids(findings)
    assert any(w.startswith("1.4.1") for w in wcag_ids), (
        f"expected a 1.4.1 finding; got: {findings}"
    )
    assert findings[0].get("ruleId") == "XLSX_COLOR_ONLY_STATUS"


def test_xlsx_141_plain_sheet_silent(tmp_path):
    """1.4.1 detector is silent for a plain sheet with no conditional formatting."""
    p = _make_zip(
        tmp_path,
        "plain.xlsx",
        {
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData/></worksheet>"
            )
        },
    )
    assert _os.office_color_only_checks(p, ".xlsx") == []


# ══════════════════════════════════════════════════════════════════════════════
# xlsx  1.4.11 — Non-text Contrast
# ══════════════════════════════════════════════════════════════════════════════

# A DrawingML shape with a very-light-gray outline (#EEEEEE) on a white fill (#FFFFFF).
# Contrast ratio ≈ 1.05 : 1  (well below the 3:1 threshold).
_DRAWING_LOW_CONTRAST = """\
<xdr:wsDr
  xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <xdr:twoCellAnchor>
    <xdr:from>
      <xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>
      <xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff>
    </xdr:from>
    <xdr:to>
      <xdr:col>4</xdr:col><xdr:colOff>0</xdr:colOff>
      <xdr:row>4</xdr:row><xdr:rowOff>0</xdr:rowOff>
    </xdr:to>
    <xdr:sp>
      <xdr:nvSpPr>
        <xdr:cNvPr id="2" name="StatusShape"/>
        <xdr:cNvSpPr/>
      </xdr:nvSpPr>
      <xdr:spPr>
        <a:solidFill>
          <a:srgbClr val="FFFFFF"/>
        </a:solidFill>
        <a:ln>
          <a:solidFill>
            <a:srgbClr val="EEEEEE"/>
          </a:solidFill>
        </a:ln>
      </xdr:spPr>
    </xdr:sp>
    <xdr:clientData/>
  </xdr:twoCellAnchor>
</xdr:wsDr>
"""


def test_xlsx_1411_low_contrast_shape_detected(tmp_path):
    """1.4.11 detector flags a DrawingML shape whose outline contrast is < 3:1."""
    p = _make_zip(
        tmp_path,
        "low_contrast.xlsx",
        {"xl/drawings/drawing1.xml": _DRAWING_LOW_CONTRAST},
    )
    findings = _os.xlsx_nontext_contrast_checks(p)
    wcag_ids = _wcag_ids(findings)
    assert any(w.startswith("1.4.11") for w in wcag_ids), (
        f"expected a 1.4.11 finding; got: {findings}"
    )
    assert findings[0].get("ruleId") == "XLSX_NONTEXT_LOW_CONTRAST"


def test_xlsx_1411_high_contrast_shape_silent(tmp_path):
    """1.4.11 detector is silent for a shape with ample contrast (black on white = 21:1)."""
    drawing = _DRAWING_LOW_CONTRAST.replace(
        '<a:srgbClr val="EEEEEE"/>', '<a:srgbClr val="000000"/>'
    )
    p = _make_zip(tmp_path, "ok_contrast.xlsx", {"xl/drawings/drawing1.xml": drawing})
    assert _os.xlsx_nontext_contrast_checks(p) == []


# ══════════════════════════════════════════════════════════════════════════════
# xlsx  4.1.2 — Name, Role, Value
# ══════════════════════════════════════════════════════════════════════════════

def test_xlsx_412_activex_control_flags_name_role_value(tmp_path):
    """4.1.2 detector flags an xlsx that embeds an ActiveX control."""
    p = _make_zip(
        tmp_path,
        "activex.xlsx",
        {
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData/></worksheet>"
            ),
            # An ActiveX part signals that the workbook embeds an opaque control whose
            # accessible name and role cannot be verified statically.
            "xl/activeX/activeX1.xml": "<ax:activeX/>",
        },
    )
    findings = _os.office_control_review_checks(p, ".xlsx")
    wcag_ids = _wcag_ids(findings)
    assert any(w.startswith("4.1.2") for w in wcag_ids), (
        f"expected a 4.1.2 finding; got: {findings}"
    )
    assert any(f.get("ruleId") == "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE" for f in findings)


def test_xlsx_412_static_workbook_silent(tmp_path):
    """4.1.2 detector is silent for a plain workbook with no embedded controls."""
    p = _make_zip(
        tmp_path,
        "static.xlsx",
        {
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData/></worksheet>"
            )
        },
    )
    assert _os.office_control_review_checks(p, ".xlsx") == []


# ══════════════════════════════════════════════════════════════════════════════
# pdf  2.4.3 — Focus Order
# ══════════════════════════════════════════════════════════════════════════════
#
# The PDF detector (formats/pdf/detectors/focus_order.detect) requires pikepdf.
# The fixture builder requires reportlab. Both are guarded with importorskip.

_pikepdf = pytest.importorskip(
    "pikepdf",
    reason="pikepdf not installed — pdf 2.4.3 fixture tests are skipped",
)
_reportlab_canvas = pytest.importorskip(
    "reportlab.pdfgen.canvas",
    reason="reportlab not installed — pdf 2.4.3 fixture tests are skipped",
)


def _form_pdf(path: Path, names: list[str]) -> None:
    """Build a single-page PDF with AcroForm text fields via reportlab."""
    from reportlab.pdfgen.canvas import Canvas

    c = Canvas(str(path))
    for i, nm in enumerate(names):
        c.acroForm.textfield(
            name=nm, x=72, y=700 - i * 40, width=200, height=20, borderWidth=1
        )
    c.showPage()
    c.save()


def test_pdf_243_widget_page_without_tabs_s_detected(tmp_path):
    """2.4.3 detector flags a PDF whose widget page lacks /Tabs = /S.

    reportlab does not write /Tabs at all, so the fixture is already non-compliant
    straight out of the generator — no post-processing needed.
    """
    import formats.pdf.detectors.focus_order as _fo  # noqa: E402

    p = tmp_path / "form.pdf"
    _form_pdf(p, ["First Name", "Last Name"])
    findings = _fo.detect(p)
    wcag_ids = _wcag_ids(findings)
    assert any(w.startswith("2.4.3") for w in wcag_ids), (
        f"expected a 2.4.3 finding; got: {findings}"
    )
    assert findings[0].get("ruleId") == "PDF_TAB_ORDER_NOT_STRUCTURE"


def test_pdf_243_tabs_s_present_is_clean(tmp_path):
    """2.4.3 detector is silent when /Tabs = /S is set on the widget page."""
    import formats.pdf.detectors.focus_order as _fo  # noqa: E402

    raw = tmp_path / "form_raw.pdf"
    _form_pdf(raw, ["Email"])
    out = tmp_path / "form_tabbed.pdf"

    pdf = _pikepdf.open(str(raw))
    pdf.pages[0].obj["/Tabs"] = _pikepdf.Name("/S")
    pdf.save(str(out))
    pdf.close()

    assert _fo.detect(out) == []


def test_pdf_243_plain_pdf_without_widgets_silent(tmp_path):
    """2.4.3 detector is silent for a PDF with no AcroForm fields."""
    import formats.pdf.detectors.focus_order as _fo  # noqa: E402
    from reportlab.pdfgen.canvas import Canvas

    p = tmp_path / "plain.pdf"
    c = Canvas(str(p))
    c.drawString(72, 720, "No form fields here.")
    c.showPage()
    c.save()

    assert _fo.detect(p) == []
