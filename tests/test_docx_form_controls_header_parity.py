"""A form control in a running header is judged like one in the body — 2.1.2 / 3.3.2 / 4.1.2.

Three docx checks read interactive form controls (w:sdt input content controls, w:ffData legacy
fields) from word/document.xml alone:

  * office_interactive_controls   → 2.1.2 No Keyboard Trap (control present at all)
  * docx_checks' w:sdt loop       → 3.3.2 Labels or Instructions (control with no w:alias title)
  * formats.docx.detectors.name_role_value.detect → 4.1.2 Name, Role, Value (same, delegated)

A clinical form routinely puts a Patient-ID or date field in a RUNNING HEADER, and a control there
is as interactive — and as trap-prone, as unlabelled — as one in the body. Reading the body alone
missed all three. This is the same header/footer/note population #214 (2.4.4), #226 (3.1.2) and
#227 (1.4.1) already read.

The body cases are controls proving the header coverage is new reach, not a change to the body's
existing behaviour.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx  # noqa: E402
from formats.docx.detectors.name_role_value import detect as name_role_detect  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _date_control(*, alias: str | None) -> str:
    """An INPUT content control (w:date gate). alias=None leaves it untitled (fails 3.3.2/4.1.2);
    a non-empty alias names it (passes)."""
    a = f'<w:alias w:val="{alias}"/>' if alias else ""
    return (f"<w:sdt><w:sdtPr>{a}<w:date/></w:sdtPr>"
            f'<w:sdtContent><w:r><w:t>__</w:t></w:r></w:sdtContent></w:sdt>')


def _ffdata_field() -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Signature"/>'
            "</w:ffData></w:fldChar></w:r>")


def _build(path: Path, *, body: str = "", header: str = "") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p>{body}</w:p></w:body></w:document>')
        if header:
            z.writestr("word/header1.xml", f'<w:hdr xmlns:w="{W}"><w:p>{header}</w:p></w:hdr>')
    return path


def _ctrl_types(path: Path) -> set[str]:
    return {c["type"] for c in osx.office_interactive_controls(path, ".docx")}


def _fires(path: Path, sc: str, detector) -> bool:
    return any(sc in str(f.get("wcag", "")) for f in detector(path))


# ── 2.1.2 — the control is seen at all ────────────────────────────────────────────────────────

def test_interactive_control_detected_in_header(tmp_path):
    p = _build(tmp_path / "hdr_cc.docx", header=_date_control(alias="Date"))
    assert "interactive content control" in _ctrl_types(p)


def test_legacy_form_field_detected_in_header(tmp_path):
    p = _build(tmp_path / "hdr_ff.docx", header=_ffdata_field())
    assert "legacy form field" in _ctrl_types(p)


# ── 3.3.2 / 4.1.2 — an UNNAMED control in a header fails, a named one does not ─────────────────

def test_unnamed_control_in_header_fails_332(tmp_path):
    p = _build(tmp_path / "hdr_332.docx", header=_date_control(alias=None))
    assert _fires(p, "3.3.2", osx.docx_checks)


def test_unnamed_control_in_header_fails_412(tmp_path):
    p = _build(tmp_path / "hdr_412.docx", header=_date_control(alias=None))
    assert _fires(p, "4.1.2", name_role_detect)


def test_named_control_in_header_passes_both(tmp_path):
    """The fix widens WHERE controls are read, not WHAT fails: a titled header control is fine."""
    p = _build(tmp_path / "hdr_named.docx", header=_date_control(alias="Patient ID"))
    assert not _fires(p, "3.3.2", osx.docx_checks)
    assert not _fires(p, "4.1.2", name_role_detect)


# ── controls: the body behaves exactly as before ──────────────────────────────────────────────

def test_unnamed_control_in_body_still_fails_both(tmp_path):
    p = _build(tmp_path / "body_unnamed.docx", body=_date_control(alias=None))
    assert _fires(p, "3.3.2", osx.docx_checks)
    assert _fires(p, "4.1.2", name_role_detect)


def test_body_with_no_control_fires_neither(tmp_path):
    p = _build(tmp_path / "body_plain.docx", body="<w:r><w:t>ordinary text</w:t></w:r>")
    assert not _fires(p, "3.3.2", osx.docx_checks)
    assert not _fires(p, "4.1.2", name_role_detect)
    assert _ctrl_types(p) == set()
