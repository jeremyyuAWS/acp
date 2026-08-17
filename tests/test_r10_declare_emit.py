"""R10 — the declare-gate for the four capability cells R8 wants to flip.

Each of these cells already has a SHIPPING detector; R8's honesty rule is that a cell may only be
DECLARED (moved off review/not-ready in the capability registry) once a test proves the detector
actually EMITS on a targeted fixture. Those proofs exist, scattered across
test_office_review_detectors.py / test_office_structure_controls.py / test_pdf_focus_order.py — this
file consolidates them into ONE named gate the R8 change can point to, and guards these four specific
cells against a future refactor silently breaking the detector a declared cell depends on.

  xlsx 1.4.1   Use of Color        office_structure.office_color_only_checks    -> XLSX_COLOR_ONLY_STATUS
  xlsx 1.4.11  Non-text Contrast   office_structure.xlsx_nontext_contrast_checks-> XLSX_NONTEXT_LOW_CONTRAST
  xlsx 4.1.2   Name/Role/Value     office_structure.office_control_review_checks-> 4.1.2 (control review)
  pdf  2.4.3   Focus Order         office_structure.pdf_focus_order_checks      -> PDF_TAB_ORDER_NOT_STRUCTURE

The xlsx legs are pure zipfile/regex (run everywhere). The pdf leg needs reportlab (build) + pikepdf
(detect); it skips where those are absent and runs in CI, which has the full engine.
"""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import office_structure as osx  # noqa: E402


def _rid(f):
    return f.get("rule_id") or f.get("ruleId")


def _zip(tmp: Path, name: str, parts: dict) -> Path:
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return p


# ── xlsx 1.4.1 — a colour-only conditional-format rule ────────────────────────────────────────
def test_xlsx_1_4_1_use_of_color_emits(tmp_path):
    p = _zip(tmp_path, "cf.xlsx", {
        "xl/worksheets/sheet1.xml":
            '<worksheet><conditionalFormatting sqref="A1:A5">'
            '<cfRule type="colorScale" priority="1"/></conditionalFormatting></worksheet>',
    })
    out = osx.office_color_only_checks(p, ".xlsx")
    assert any(_rid(f) == "XLSX_COLOR_ONLY_STATUS" and f["wcag"].startswith("1.4.1") for f in out), out


# ── xlsx 1.4.11 — a shape outline with <3:1 contrast on its fill ───────────────────────────────
def test_xlsx_1_4_11_non_text_contrast_emits(tmp_path):
    drawing = (
        '<xdr:wsDr xmlns:xdr="x" xmlns:a="a"><xdr:oneCellAnchor><xdr:sp><xdr:spPr>'
        '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
        '<a:ln><a:solidFill><a:srgbClr val="F2F2F2"/></a:solidFill></a:ln>'
        '</xdr:spPr></xdr:sp></xdr:oneCellAnchor></xdr:wsDr>'
    )
    p = _zip(tmp_path, "shape.xlsx", {
        "xl/worksheets/sheet1.xml": "<worksheet/>",
        "xl/drawings/drawing1.xml": drawing,
    })
    out = osx.xlsx_nontext_contrast_checks(p)
    assert any(_rid(f) == "XLSX_NONTEXT_LOW_CONTRAST" and f["wcag"].startswith("1.4.11") for f in out), out


# ── xlsx 4.1.2 — an embedded ActiveX control whose name/role can't be proven statically ─────────
def test_xlsx_4_1_2_name_role_value_emits(tmp_path):
    p = _zip(tmp_path, "ctrl.xlsx", {
        "xl/worksheets/sheet1.xml": "<worksheet/>",
        "xl/activeX/activeX1.xml": "<ax/>",
    })
    out = osx.office_control_review_checks(p, ".xlsx")
    assert any(f["wcag"].startswith("4.1.2") for f in out), out


# ── pdf 2.4.3 — a page carrying form widgets with no /Tabs = /S ─────────────────────────────────
def test_pdf_2_4_3_focus_order_emits(tmp_path):
    pytest.importorskip("pikepdf")
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    p = tmp_path / "form.pdf"
    c = reportlab.Canvas(str(p))
    c.acroForm.textfield(name="First Name", x=72, y=700, width=200, height=20, borderWidth=1)
    c.showPage()
    c.save()
    out = osx.pdf_focus_order_checks(p)
    assert any(_rid(f) == "PDF_TAB_ORDER_NOT_STRUCTURE" and f["wcag"].startswith("2.4.3") for f in out), out
