"""Interactive-control detector for the Review-Recommended lane (ADR 0023, Phase 1a).

`office_interactive_controls` / `office_control_review_checks` surface embedded
interactive controls (ActiveX, OLE, VBA, content-control form fields, legacy form
fields, worksheet form controls) as advisory REVIEW findings for 2.1.2 + 4.1.2 — a
concrete, evidence-backed signal a human must adjudicate, never a fabricated pass.
A static document with no controls yields nothing (→ the criteria stay genuine N/A).

Fixtures are hand-built zips (same posture as test_office_structure.py) — no
python-docx/pptx dependency.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402

_MIN_DOC = "<w:document><w:body/></w:document>"


def _zip(tmp: Path, name: str, parts: dict[str, str | bytes]) -> Path:
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return p


def _types(controls: list[dict]) -> dict[str, int]:
    return {c["type"]: c["count"] for c in controls}


# ── static documents → no signal, genuine N/A ────────────────────────────────
def test_static_docx_has_no_controls(tmp_path):
    p = _zip(tmp_path, "static.docx", {"word/document.xml": _MIN_DOC})
    assert os_.office_interactive_controls(p, ".docx") == []
    assert os_.office_control_review_checks(p, ".docx") == []


def test_static_pptx_has_no_controls(tmp_path):
    p = _zip(tmp_path, "static.pptx", {"ppt/slides/slide1.xml": "<p:sld/>"})
    assert os_.office_control_review_checks(p, ".pptx") == []


def test_static_xlsx_has_no_controls(tmp_path):
    p = _zip(tmp_path, "static.xlsx", {"xl/worksheets/sheet1.xml": "<worksheet/>"})
    assert os_.office_control_review_checks(p, ".xlsx") == []


def test_non_office_ext_ignored(tmp_path):
    p = _zip(tmp_path, "x.pdf", {"word/activeX/activeX1.xml": "<ax/>"})
    assert os_.office_interactive_controls(p, ".pdf") == []


# ── each control kind is detected ────────────────────────────────────────────
def test_activex_control_detected(tmp_path):
    p = _zip(tmp_path, "ax.docx", {
        "word/document.xml": _MIN_DOC,
        "word/activeX/activeX1.xml": "<ax/>",
        "word/activeX/activeX2.xml": "<ax/>",
    })
    assert _types(os_.office_interactive_controls(p, ".docx")) == {"ActiveX control": 2}


def test_embedded_ole_object_detected(tmp_path):
    p = _zip(tmp_path, "ole.pptx", {
        "ppt/slides/slide1.xml": "<p:sld/>",
        "ppt/embeddings/oleObject1.bin": "\x00",
    })
    assert _types(os_.office_interactive_controls(p, ".pptx")) == {"embedded OLE object": 1}


def test_vba_macro_project_detected(tmp_path):
    p = _zip(tmp_path, "macro.xlsx", {
        "xl/worksheets/sheet1.xml": "<worksheet/>",
        "xl/vbaProject.bin": "\x00",
    })
    assert _types(os_.office_interactive_controls(p, ".xlsx")) == {"VBA macro project": 1}


def test_xlsx_form_control_detected(tmp_path):
    p = _zip(tmp_path, "form.xlsx", {
        "xl/worksheets/sheet1.xml": "<worksheet/>",
        "xl/ctrlProps/ctrlProp1.xml": "<formControlPr/>",
    })
    assert _types(os_.office_interactive_controls(p, ".xlsx")) == {"form control": 1}


def test_docx_content_control_input_detected(tmp_path):
    doc = ("<w:document><w:body>"
           "<w:sdt><w:sdtPr><w:checkbox/></w:sdtPr><w:sdtContent/></w:sdt>"
           "</w:body></w:document>")
    p = _zip(tmp_path, "cc.docx", {"word/document.xml": doc})
    assert _types(os_.office_interactive_controls(p, ".docx")) == {"interactive content control": 1}


def test_docx_non_input_content_control_not_counted(tmp_path):
    # A TOC / rich-text placeholder sdt has no input type — not an interactive control.
    doc = ("<w:document><w:body>"
           "<w:sdt><w:sdtPr><w:docPartObj/></w:sdtPr><w:sdtContent/></w:sdt>"
           "</w:body></w:document>")
    p = _zip(tmp_path, "toc.docx", {"word/document.xml": doc})
    assert os_.office_interactive_controls(p, ".docx") == []


def test_docx_legacy_form_field_detected(tmp_path):
    doc = "<w:document><w:body><w:fldChar><w:ffData><w:checkBox/></w:ffData></w:fldChar></w:body></w:document>"
    p = _zip(tmp_path, "legacy.docx", {"word/document.xml": doc})
    assert _types(os_.office_interactive_controls(p, ".docx")) == {"legacy form field": 1}


# ── review findings: shape, advisory flag, both criteria, evidence in detail ──
def test_review_findings_cover_both_criteria(tmp_path):
    p = _zip(tmp_path, "ax.docx", {
        "word/document.xml": _MIN_DOC,
        "word/activeX/activeX1.xml": "<ax/>",
    })
    findings = os_.office_control_review_checks(p, ".docx")
    wcags = {f["wcag"] for f in findings}
    assert wcags == {"2.1.2 No Keyboard Trap", "4.1.2 Name, Role, Value"}
    for f in findings:
        assert f["severity"] == "REVIEW"
        assert f["advisory"] is True
        assert "1 ActiveX control" in f["detail"]   # singular, real count in evidence


def test_review_evidence_lists_multiple_control_kinds(tmp_path):
    p = _zip(tmp_path, "mixed.docx", {
        "word/document.xml": _MIN_DOC,
        "word/activeX/activeX1.xml": "<ax/>",
        "word/activeX/activeX2.xml": "<ax/>",
        "word/vbaProject.bin": "\x00",
    })
    detail = os_.office_control_review_checks(p, ".docx")[0]["detail"]
    assert "2 ActiveX controls" in detail
    assert "1 VBA macro project" in detail


def test_checks_for_includes_control_review(tmp_path):
    # End-to-end through the dispatcher the scanner calls.
    p = _zip(tmp_path, "ax.pptx", {
        "ppt/slides/slide1.xml": "<p:sld/>",
        "ppt/activeX/activeX1.xml": "<ax/>",
    })
    rules = {f["ruleId"] for f in os_.checks_for(p, ".pptx")}
    assert "OFFICE_INTERACTIVE_CONTROL_KEYBOARD" in rules
    assert "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE" in rules


def test_corrupt_zip_never_raises(tmp_path):
    p = tmp_path / "corrupt.docx"
    p.write_bytes(b"not a zip")
    assert os_.office_interactive_controls(p, ".docx") == []
    assert os_.office_control_review_checks(p, ".docx") == []
