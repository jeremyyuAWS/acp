"""P-22: 2.4.3 Focus Order — PDF StructTreeRoot vs AcroForm comparison.

Extends the existing /Tabs = /S heuristic with a direct widget-order comparison:
  • When both AcroForm and /StructTreeRoot are present, collect widget object numbers
    from the field tree (= tab order) and from OBJR entries in the structure tree
    (= reading order). Any inversion in the matched set is flagged as
    PDF_FOCUS_ORDER_STRUCT_MISMATCH.
  • When no StructTreeRoot is present (untagged PDF), fall back to the /Tabs = /S
    heuristic (PDF_TAB_ORDER_NOT_STRUCTURE) — unchanged behaviour from before this PR.

Coverage upgrade: HEURISTIC → PARTIAL (direct comparison within scope).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pikepdf = pytest.importorskip("pikepdf")

from formats.pdf.detectors.focus_order import detect  # noqa: E402


# ── PDF builder helpers ────────────────────────────────────────────────────────

def _make_text_widget(pdf, name: str, rect) -> pikepdf.Dictionary:
    """Create a minimal text-field widget annotation and add it to the PDF as indirect."""
    widget = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Widget"),
        FT=pikepdf.Name("/Tx"),
        T=pikepdf.String(name),
        TU=pikepdf.String(f"Enter {name}"),
        Rect=pikepdf.Array([pikepdf.Real(x) for x in rect]),
        P=pdf.pages[0].obj,        # filled in by caller if needed
    ))
    return widget


def _pdf_with_two_fields_correct_order(tmp: Path) -> Path:
    """AcroForm field tree order [F1, F2] matches StructTreeRoot OBJR order [F1, F2]."""
    p = tmp / "correct.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, 612, 792]),
        Tabs=pikepdf.Name("/S"),
    )
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(page_ref)

    w1 = _make_text_widget(pdf, "Field1", [72, 700, 200, 720])
    w2 = _make_text_widget(pdf, "Field2", [72, 650, 200, 670])

    # Put both widgets on the page
    page_ref["/Annots"] = pikepdf.Array([w1, w2])

    # AcroForm: F1 first, F2 second (matches reading order top-to-bottom)
    acro = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([w1, w2]),
    ))
    pdf.Root["/AcroForm"] = acro

    # StructTreeRoot with OBJRs in same order: F1 then F2
    objr1 = pikepdf.Dictionary(Type=pikepdf.Name("/OBJR"), Obj=w1)
    objr2 = pikepdf.Dictionary(Type=pikepdf.Name("/OBJR"), Obj=w2)
    struct_elem = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/StructElem"),
        S=pikepdf.Name("/Form"),
        K=pikepdf.Array([objr1, objr2]),
    ))
    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/StructTreeRoot"),
        K=struct_elem,
    ))

    pdf.save(str(p))
    return p


def _pdf_with_two_fields_wrong_order(tmp: Path) -> Path:
    """AcroForm field tree order [F1, F2] but StructTreeRoot OBJR order [F2, F1] — mismatch."""
    p = tmp / "wrong.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, 612, 792]),
        Tabs=pikepdf.Name("/S"),  # /Tabs = /S is set — old check would miss this
    )
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(page_ref)

    w1 = _make_text_widget(pdf, "Field1", [72, 700, 200, 720])
    w2 = _make_text_widget(pdf, "Field2", [72, 650, 200, 670])

    page_ref["/Annots"] = pikepdf.Array([w1, w2])

    # AcroForm: F1 first (tab order: F1 → F2)
    acro = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([w1, w2]),
    ))
    pdf.Root["/AcroForm"] = acro

    # StructTreeRoot: F2 first (reading order: F2 before F1) — REVERSED vs tab order
    objr1 = pikepdf.Dictionary(Type=pikepdf.Name("/OBJR"), Obj=w1)
    objr2 = pikepdf.Dictionary(Type=pikepdf.Name("/OBJR"), Obj=w2)
    struct_elem = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/StructElem"),
        S=pikepdf.Name("/Form"),
        K=pikepdf.Array([objr2, objr1]),  # note: reversed
    ))
    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/StructTreeRoot"),
        K=struct_elem,
    ))

    pdf.save(str(p))
    return p


def _pdf_no_struct_tabs_missing(tmp: Path) -> Path:
    """Untagged PDF (no StructTreeRoot), page has a widget but /Tabs is absent → heuristic fires."""
    p = tmp / "notabs.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, 612, 792]),
        # no /Tabs entry
    )
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(page_ref)

    w1 = _make_text_widget(pdf, "Field1", [72, 700, 200, 720])
    page_ref["/Annots"] = pikepdf.Array([w1])

    acro = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array([w1])))
    pdf.Root["/AcroForm"] = acro
    # no /StructTreeRoot

    pdf.save(str(p))
    return p


def _pdf_no_struct_tabs_set(tmp: Path) -> Path:
    """Untagged PDF, /Tabs = /S is set → heuristic finds nothing (clean)."""
    p = tmp / "notabs_ok.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, 612, 792]),
        Tabs=pikepdf.Name("/S"),
    )
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(page_ref)

    w1 = _make_text_widget(pdf, "Field1", [72, 700, 200, 720])
    page_ref["/Annots"] = pikepdf.Array([w1])

    acro = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array([w1])))
    pdf.Root["/AcroForm"] = acro

    pdf.save(str(p))
    return p


def _pdf_no_fields(tmp: Path) -> Path:
    """PDF with no AcroForm — nothing to assess, must return empty."""
    p = tmp / "nofields.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(Type=pikepdf.Name("/Page"), MediaBox=pikepdf.Array([0, 0, 612, 792]))
    pdf.pages.append(pdf.make_indirect(page))
    pdf.save(str(p))
    return p


# ── tests ─────────────────────────────────────────────────────────────────────

def test_correct_order_not_flagged(tmp_path):
    """AcroForm tab order matches StructTreeRoot reading order → no finding."""
    results = detect(_pdf_with_two_fields_correct_order(tmp_path))
    assert results == [], f"correct order was wrongly flagged: {results}"


def test_wrong_order_flagged_with_struct_mismatch(tmp_path):
    """AcroForm tab order reversed vs StructTreeRoot → PDF_FOCUS_ORDER_STRUCT_MISMATCH."""
    results = detect(_pdf_with_two_fields_wrong_order(tmp_path))
    rule_ids = {r.get("ruleId") for r in results}
    assert "PDF_FOCUS_ORDER_STRUCT_MISMATCH" in rule_ids, (
        "reversed field order not detected: got " + str(results))


def test_struct_mismatch_finding_has_correct_wcag(tmp_path):
    results = detect(_pdf_with_two_fields_wrong_order(tmp_path))
    mismatch = [r for r in results if r.get("ruleId") == "PDF_FOCUS_ORDER_STRUCT_MISMATCH"]
    assert mismatch, "PDF_FOCUS_ORDER_STRUCT_MISMATCH finding missing"
    assert "2.4.3" in mismatch[0].get("wcag", "")


def test_wrong_order_does_not_emit_tabs_finding_when_struct_available(tmp_path):
    """When the struct comparison runs and finds a mismatch, /Tabs check is not also emitted."""
    results = detect(_pdf_with_two_fields_wrong_order(tmp_path))
    rule_ids = {r.get("ruleId") for r in results}
    assert "PDF_TAB_ORDER_NOT_STRUCTURE" not in rule_ids, (
        "legacy /Tabs finding emitted alongside struct-mismatch finding")


def test_untagged_pdf_missing_tabs_uses_heuristic(tmp_path):
    """/Tabs fallback: no StructTreeRoot, /Tabs absent → PDF_TAB_ORDER_NOT_STRUCTURE."""
    results = detect(_pdf_no_struct_tabs_missing(tmp_path))
    rule_ids = {r.get("ruleId") for r in results}
    assert "PDF_TAB_ORDER_NOT_STRUCTURE" in rule_ids, (
        "heuristic /Tabs check did not fire on untagged PDF without /Tabs")


def test_untagged_pdf_with_tabs_set_is_clean(tmp_path):
    """/Tabs fallback: no StructTreeRoot, /Tabs = /S → nothing flagged."""
    results = detect(_pdf_no_struct_tabs_set(tmp_path))
    assert results == [], f"clean untagged PDF was wrongly flagged: {results}"


def test_no_form_fields_returns_empty(tmp_path):
    """PDF without AcroForm → detector returns [] without error."""
    assert detect(_pdf_no_fields(tmp_path)) == []


def test_registry_coverage_upgraded_to_partial():
    """The registry declaration now says PARTIAL, not HEURISTIC."""
    import rule_registry
    from assessment import Coverage
    rule_registry.load()
    cov = rule_registry.coverage_for("2.4.3", "pdf")
    assert cov is Coverage.PARTIAL, (
        f"2.4.3 × pdf coverage should be PARTIAL after struct-tree comparison added; got {cov}")
