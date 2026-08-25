"""P-24: 2.5.3 Label in Name — PDF push-button detector.

Push buttons are the only AcroForm field type where both the visible label (/MK /CA
caption) and the accessible name (/TU or /T) live in the same field object and can be
compared directly. The check: the accessible name must CONTAIN the caption text
(case-insensitive). Coverage: PARTIAL (push buttons only), Confidence: HIGH.

Rule ID: PDF_LABEL_NOT_IN_NAME
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pikepdf = pytest.importorskip("pikepdf")

from formats.pdf.detectors.label_in_name import detect  # noqa: E402


# ── PDF fixture builders ───────────────────────────────────────────────────────────────

_PUSHBUTTON_FLAG = 1 << 16   # Ff bit 17 (PDF spec 1-indexed) = bit 16 (0-indexed)


def _push_button(pdf, caption: str | None, tooltip: str | None, field_name: str) -> pikepdf.Dictionary:
    """Create an indirect push-button widget with the given caption (/MK /CA) and tooltip (/TU)."""
    kw = dict(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Widget"),
        FT=pikepdf.Name("/Btn"),
        Ff=pikepdf.Integer(_PUSHBUTTON_FLAG),
        T=pikepdf.String(field_name),
        Rect=pikepdf.Array([pikepdf.Real(x) for x in [72, 700, 150, 720]]),
    )
    if tooltip is not None:
        kw["TU"] = pikepdf.String(tooltip)
    if caption is not None:
        kw["MK"] = pikepdf.Dictionary(CA=pikepdf.String(caption))
    return pdf.make_indirect(pikepdf.Dictionary(**kw))


def _pdf_with_button(tmp: Path, fname: str, caption: str | None,
                     tooltip: str | None, field_name: str = "btn1") -> Path:
    p = tmp / fname
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, 612, 792]),
    )
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(pikepdf.Page(page_ref))

    btn = _push_button(pdf, caption, tooltip, field_name)
    page_ref["/Annots"] = pikepdf.Array([btn])
    pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([btn])
    ))
    pdf.save(str(p))
    return p


def _pdf_no_fields(tmp: Path) -> Path:
    p = tmp / "nofields.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(Type=pikepdf.Name("/Page"), MediaBox=pikepdf.Array([0, 0, 612, 792]))
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    pdf.save(str(p))
    return p


def _pdf_text_field(tmp: Path) -> Path:
    """Text field (not a push button) — outside scope; must not be flagged."""
    p = tmp / "textfield.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(Type=pikepdf.Name("/Page"), MediaBox=pikepdf.Array([0, 0, 612, 792]))
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(pikepdf.Page(page_ref))

    widget = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Widget"),
        FT=pikepdf.Name("/Tx"),
        T=pikepdf.String("textfield1"),
        TU=pikepdf.String("unrelated name"),
        Rect=pikepdf.Array([pikepdf.Real(x) for x in [72, 700, 200, 720]]),
    ))
    page_ref["/Annots"] = pikepdf.Array([widget])
    pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([widget])
    ))
    pdf.save(str(p))
    return p


# ── tests ──────────────────────────────────────────────────────────────────────────────

def test_caption_in_tooltip_passes(tmp_path):
    """Caption 'Submit' contained in /TU 'Submit this form' → no finding."""
    results = detect(_pdf_with_button(tmp_path, "ok.pdf", "Submit", "Submit this form"))
    assert results == [], results


def test_caption_equals_tooltip_passes(tmp_path):
    """Caption equals /TU exactly → no finding."""
    results = detect(_pdf_with_button(tmp_path, "exact.pdf", "Go", "Go"))
    assert results == [], results


def test_caption_case_insensitive_passes(tmp_path):
    """Case-insensitive match: caption 'SEARCH' in /TU 'search results' → no finding."""
    results = detect(_pdf_with_button(tmp_path, "case.pdf", "SEARCH", "search results"))
    assert results == [], results


def test_caption_not_in_tooltip_flagged(tmp_path):
    """Caption 'Submit' absent from /TU 'btn_primary' → PDF_LABEL_NOT_IN_NAME."""
    results = detect(_pdf_with_button(tmp_path, "fail.pdf", "Submit", "btn_primary"))
    assert any(r.get("ruleId") == "PDF_LABEL_NOT_IN_NAME" for r in results), results


def test_caption_not_in_field_name_fallback_flagged(tmp_path):
    """No /TU — fallback to /T 'btn1': caption 'Submit' not in 'btn1' → flagged."""
    results = detect(_pdf_with_button(tmp_path, "fallback.pdf", "Submit", None, field_name="btn1"))
    assert any(r.get("ruleId") == "PDF_LABEL_NOT_IN_NAME" for r in results), results


def test_caption_in_field_name_fallback_passes(tmp_path):
    """No /TU — fallback to /T 'submit_button': caption 'Submit' in 'submit_button' → no finding."""
    results = detect(_pdf_with_button(tmp_path, "fallback_ok.pdf", "Submit", None,
                                      field_name="submit_button"))
    assert results == [], results


def test_no_caption_not_flagged(tmp_path):
    """Push button without /MK /CA — no visible caption to compare → no finding."""
    results = detect(_pdf_with_button(tmp_path, "nocap.pdf", None, "btn_primary"))
    assert results == [], results


def test_non_pushbutton_not_flagged(tmp_path):
    """Text field (not a push button) — out of scope → no finding even with mismatch."""
    results = detect(_pdf_text_field(tmp_path))
    assert results == [], results


def test_no_fields_returns_empty(tmp_path):
    """PDF with no AcroForm → []."""
    assert detect(_pdf_no_fields(tmp_path)) == []


def test_finding_severity_is_serious(tmp_path):
    """Finding is SERIOUS — speech-input users are completely blocked."""
    results = detect(_pdf_with_button(tmp_path, "sev.pdf", "Submit", "btn_primary"))
    match = [r for r in results if r.get("ruleId") == "PDF_LABEL_NOT_IN_NAME"]
    assert match and match[0].get("severity") == "SERIOUS", match


def test_finding_wcag_tag(tmp_path):
    """Finding carries the correct WCAG criterion tag."""
    results = detect(_pdf_with_button(tmp_path, "wcag.pdf", "Submit", "btn_primary"))
    match = [r for r in results if r.get("ruleId") == "PDF_LABEL_NOT_IN_NAME"]
    assert match and "2.5.3" in match[0].get("wcag", ""), match


def test_registry_2_5_3_pdf_declared():
    """pdf × 2.5.3 is now declared in the registry (was —)."""
    import rule_registry
    from assessment import Coverage
    rule_registry.load()
    cov = rule_registry.coverage_for("2.5.3", "pdf")
    assert cov is Coverage.PARTIAL, f"2.5.3 × pdf should be PARTIAL; got {cov}"
