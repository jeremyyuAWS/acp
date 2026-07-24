"""PDF 2.4.3 (Focus Order) — AcroForm widget pages missing a /Tabs = /S (structure order) entry.

Detect: a page carrying interactive form-field widgets whose /Tabs entry is missing or isn't /S.
Remediate: set /Tabs = /S deterministically on every such page.

Scope: existence-check only (does the page declare structure-order tabbing at all), NOT whether
the AcroForm field order itself matches visual/reading order — that needs /StructTreeRoot walking
this codebase doesn't do, a separate, larger, explicitly out-of-scope gap.
pikepdf/reportlab-only — no partner engine needed.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import office_structure as OSX  # noqa: E402
import remediate_pdf as RP  # noqa: E402


def _form_pdf(path: Path, names: list[str]) -> None:
    c = canvas.Canvas(str(path))
    for i, nm in enumerate(names):
        c.acroForm.textfield(name=nm, x=72, y=700 - i * 40, width=200, height=20, borderWidth=1)
    c.showPage()
    c.save()


def _plain_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path)); c.drawString(72, 720, "no form here"); c.showPage(); c.save()


# ── detection ───────────────────────────────────────────────────────────────
def test_widget_page_without_tabs_flagged(tmp_path):
    p = tmp_path / "form.pdf"; _form_pdf(p, ["First Name"])
    findings = OSX.pdf_focus_order_checks(p)
    assert len(findings) == 1
    assert findings[0]["wcag"].startswith("2.4.3")
    assert findings[0]["ruleId"] == "PDF_TAB_ORDER_NOT_STRUCTURE"


def test_widget_page_with_tabs_s_not_flagged(tmp_path):
    p = tmp_path / "form.pdf"; _form_pdf(p, ["First Name"])
    out = tmp_path / "tabbed.pdf"
    pdf = pikepdf.open(str(p))
    pdf.pages[0].obj["/Tabs"] = pikepdf.Name("/S")
    pdf.save(str(out)); pdf.close()
    assert OSX.pdf_focus_order_checks(out) == []


def test_page_without_widgets_not_flagged(tmp_path):
    """A page with no AcroForm widgets has nothing to tab through — /Tabs is moot there."""
    p = tmp_path / "plain.pdf"; _plain_pdf(p)
    assert OSX.pdf_focus_order_checks(p) == []


def test_no_acroform_is_clean(tmp_path):
    p = tmp_path / "plain.pdf"; _plain_pdf(p)
    assert OSX.pdf_focus_order_checks(p) == []


def test_wrong_tabs_value_flagged(tmp_path):
    """/Tabs present but not /S (e.g. legacy /O document order) still fails the check."""
    p = tmp_path / "form.pdf"; _form_pdf(p, ["First Name"])
    out = tmp_path / "wrong.pdf"
    pdf = pikepdf.open(str(p))
    pdf.pages[0].obj["/Tabs"] = pikepdf.Name("/O")
    pdf.save(str(out)); pdf.close()
    assert len(OSX.pdf_focus_order_checks(out)) == 1


def test_corrupt_pdf_never_raises(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf")
    assert OSX.pdf_focus_order_checks(p) == []


# ── remediation ───────────────────────────────────────────────────────────────
def test_remediate_pdf_sets_tabs_on_widget_pages(tmp_path):
    p = tmp_path / "form.pdf"; _form_pdf(p, ["First Name"])
    out_path, applied, skipped = RP.remediate_pdf(p)
    assert out_path is not None
    assert any("2.4.3" in a for a in applied)
    fixed = pikepdf.open(str(out_path))
    assert str(fixed.pages[0].obj.get("/Tabs")) == "/S"
    fixed.close()
    # re-running the detector on the remediated file finds nothing left to flag
    assert OSX.pdf_focus_order_checks(out_path) == []


def test_remediate_pdf_leaves_already_correct_tabs_alone(tmp_path):
    p = tmp_path / "form.pdf"; _form_pdf(p, ["First Name"])
    pre = tmp_path / "pre-tabbed.pdf"
    pdf = pikepdf.open(str(p))
    pdf.pages[0].obj["/Tabs"] = pikepdf.Name("/S")
    pdf.save(str(pre)); pdf.close()
    out_path, applied, skipped = RP.remediate_pdf(pre)
    # /Tabs was already correct, so the 2.4.3 fixer contributes nothing — but other Stage 1
    # fixers (the field's missing /TU) still apply, so out_path may be non-None regardless.
    assert not any("2.4.3" in a for a in applied)
