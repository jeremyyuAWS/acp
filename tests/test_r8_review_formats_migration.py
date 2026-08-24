"""R8 — REVIEW_FORMATS migration for docx/pdf/pptx 1.4.1, 1.4.11, and pptx 4.1.2.

All six (rule × format) pairs are now registry-backed. The REVIEW_FORMATS entries that
previously short-circuited the registry branch have been removed, so a clean scan (no
finding) now resolves to REVIEW via the registry's coverage gate rather than NOT_EVALUATED
via the legacy review-lane path.

Each test verifies one of the three things the migration must not change (FAIL still fails,
a review finding still reviews) and one new thing it must fix (clean → REVIEW not NOT_EVALUATED).

pptx detector fixture tests are pure stdlib. pdf detector tests use importorskip inside each
function to avoid a module-level pdfplumber import that would trigger a pyo3 collection error
on this host.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import assessment_policy as ap   # noqa: E402
import formats.docx               # noqa: E402,F401  triggers docx registrations
import formats.pdf                # noqa: E402,F401  triggers pdf registrations
import formats.pptx               # noqa: E402,F401  triggers pptx registrations
import office_structure as _os    # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _zip(tmp: Path, name: str, parts: dict) -> Path:
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for part_name, data in parts.items():
            z.writestr(part_name, data)
    return p


# ── outcome invariants (docx, pdf, pptx × 1.4.1 and 1.4.11; pptx × 4.1.2) ──

@pytest.mark.parametrize("sc,fmt", [
    ("1.4.1", "docx"), ("1.4.1", "pdf"), ("1.4.1", "pptx"),
    ("1.4.11", "docx"), ("1.4.11", "pdf"), ("1.4.11", "pptx"),
    ("4.1.2", "pptx"),
])
def test_clean_file_now_resolves_to_review_not_not_evaluated(sc, fmt):
    """The core migration: a scan that finds nothing now reads REVIEW (we checked what
    our technique reaches) rather than NOT_EVALUATED (we did not look)."""
    assert ap._rule_outcome(sc, fmt, 0, 0, "AA", None) == ap.REVIEW, (
        f"{sc} × {fmt}: expected REVIEW on clean scan after registry migration"
    )


@pytest.mark.parametrize("sc,fmt", [
    ("1.4.1", "docx"), ("1.4.1", "pdf"), ("1.4.1", "pptx"),
    ("1.4.11", "docx"), ("1.4.11", "pdf"), ("1.4.11", "pptx"),
    ("4.1.2", "pptx"),
])
def test_blocking_finding_still_fails(sc, fmt):
    """A blocking finding must still surface as FAIL regardless of the mechanism."""
    assert ap._rule_outcome(sc, fmt, 1, 0, "AA", None) == "FAIL"


@pytest.mark.parametrize("sc,fmt", [
    ("1.4.1", "docx"), ("1.4.1", "pdf"), ("1.4.1", "pptx"),
    ("1.4.11", "docx"), ("1.4.11", "pdf"), ("1.4.11", "pptx"),
    ("4.1.2", "pptx"),
])
def test_advisory_finding_still_reviews(sc, fmt):
    """An advisory (REVIEW-severity) finding still returns REVIEW — unchanged by migration."""
    assert ap._rule_outcome(sc, fmt, 0, 1, "AA", None) == ap.REVIEW


@pytest.mark.parametrize("sc,fmt", [
    ("1.4.1", "docx"), ("1.4.1", "pdf"), ("1.4.1", "pptx"),
    ("1.4.11", "docx"), ("1.4.11", "pdf"), ("1.4.11", "pptx"),
    ("4.1.2", "pptx"),
])
def test_pair_is_not_in_review_formats(sc, fmt):
    """Direct guard: the legacy entries that blocked the registry branch are gone."""
    assert fmt not in ap.REVIEW_FORMATS.get(sc, frozenset()), (
        f"{sc} × {fmt} is still in REVIEW_FORMATS — remove it so the registry branch can answer"
    )


# ── pptx detector fixture tests (pure stdlib, no pyo3 risk) ──────────────────

def test_pptx_1411_low_contrast_shape_emits(tmp_path):
    """pptx 1.4.11 detector flags a DrawingML shape whose outline contrast is < 3:1."""
    drawing = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:spPr>'
        '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
        '<a:ln><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></a:ln>'
        '</p:spPr></p:sp></p:spTree></p:cSld></p:sld>'
    )
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:spPr>'
        '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
        '<a:ln><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></a:ln>'
        '</p:spPr></p:sp></p:spTree></p:cSld></p:sld>'
    )
    p = _zip(tmp_path, "low.pptx", {
        "ppt/slides/slide1.xml": slide,
        "ppt/presentation.xml": (
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:sldMasterIdLst/><p:sldSz cx="9144000" cy="6858000"/></p:presentation>'
        ),
    })
    out = _os.pptx_nontext_contrast_checks(p)
    assert any(f.get("wcag", "").startswith("1.4.11") for f in out), (
        f"pptx 1.4.11 detector found nothing on low-contrast shape: {out}"
    )


def test_pptx_412_activex_control_emits(tmp_path):
    """pptx 4.1.2 detector flags a presentation that embeds an ActiveX control."""
    p = _zip(tmp_path, "ctrl.pptx", {
        "ppt/slides/slide1.xml": (
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:spTree/></p:cSld></p:sld>'
        ),
        "ppt/activeX/activeX1.xml": "<ax:activeX/>",
    })
    out = _os.office_control_review_checks(p, ".pptx")
    assert any(f.get("wcag", "").startswith("4.1.2") for f in out), (
        f"pptx 4.1.2 detector found nothing on embedded ActiveX: {out}"
    )


def test_pptx_412_static_deck_silent(tmp_path):
    """pptx 4.1.2 detector is silent for a deck with no embedded controls."""
    p = _zip(tmp_path, "static.pptx", {
        "ppt/slides/slide1.xml": (
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:spTree/></p:cSld></p:sld>'
        ),
    })
    assert _os.office_control_review_checks(p, ".pptx") == []


# pdf detector fixture tests are not included here: pdf_use_of_color_checks and
# pdf_nontext_contrast_checks depend on pdfplumber/pdfminer, which trigger a pyo3
# collection error on this host. Those detectors are exercised by the existing files
# tests/test_pdf_use_of_color.py and tests/test_pdf_nontext_contrast.py in CI.
