"""PDF 4.1.2 (Name, Role, Value) — AcroForm field accessible names (/TU).

Detect: an interactive form field with no /TU is announced only by its cryptic internal name.
Remediate: a field whose own name (/T) reads like a label gets /TU set deterministically (no
model); a generic auto-name ('Text1') defers to a per-field review card + write-back on approval.
pikepdf/reportlab-only — no partner engine needed.
"""
from __future__ import annotations
import io
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
    """A 1-page PDF with a text field per name, NONE given a tooltip (/TU) → all unnamed."""
    c = canvas.Canvas(str(path))
    for i, nm in enumerate(names):
        c.acroForm.textfield(name=nm, x=72, y=700 - i * 40, width=200, height=20, borderWidth=1)
    c.showPage()
    c.save()


def _tus(data_or_path) -> dict:
    """{/T: /TU} for every terminal field."""
    pdf = pikepdf.open(io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else str(data_or_path))
    out = {}
    for f in RP._collect_form_fields(pdf):
        out[str(f.get("/T", ""))] = str(f.get("/TU", ""))
    pdf.close()
    return out


# ── detection ───────────────────────────────────────────────────────────────
def test_detects_unnamed_form_fields(tmp_path):
    p = tmp_path / "form.pdf"; _form_pdf(p, ["First Name", "Text1"])
    findings = OSX.pdf_form_field_checks(p)
    assert len(findings) == 2
    assert all(f["wcag"].startswith("4.1.2") for f in findings)


def test_named_field_not_flagged(tmp_path):
    p = tmp_path / "named.pdf"; _form_pdf(p, ["First Name"])
    named = tmp_path / "named-tu.pdf"
    # give it a /TU (save to a new file — pikepdf won't overwrite the file it opened), then
    # it must NOT be flagged.
    pdf = pikepdf.open(str(p))
    RP._collect_form_fields(pdf)[0]["/TU"] = pikepdf.String("First name")
    pdf.save(str(named)); pdf.close()
    assert OSX.pdf_form_field_checks(named) == []


def test_no_acroform_is_clean(tmp_path):
    p = tmp_path / "plain.pdf"
    c = canvas.Canvas(str(p)); c.drawString(72, 720, "no form here"); c.showPage(); c.save()
    assert OSX.pdf_form_field_checks(p) == []


# ── deterministic remediation from a meaningful field name ───────────────────
def test_meaningful_name_sets_TU_deterministically(tmp_path):
    p = tmp_path / "m.pdf"; _form_pdf(p, ["First Name"])
    pdf = pikepdf.open(str(p)); props = []
    applied, deferred = RP._fix_pdf_form_fields(pdf, proposals=props, applied_fixes=[])
    assert deferred == 0 and props == []
    assert any("4.1.2" in a for a in applied)
    out = io.BytesIO(); pdf.save(out)
    assert _tus(out.getvalue())["First Name"] == "First Name"


def test_camel_case_field_name_humanized(tmp_path):
    p = tmp_path / "c.pdf"; _form_pdf(p, ["dateOfBirth"])
    pdf = pikepdf.open(str(p))
    RP._fix_pdf_form_fields(pdf, proposals=[], applied_fixes=[])
    out = io.BytesIO(); pdf.save(out)
    assert _tus(out.getvalue())["dateOfBirth"] == "Date Of Birth"


# ── generic auto-name defers to a review card ────────────────────────────────
def test_generic_name_defers_to_proposal(tmp_path):
    p = tmp_path / "g.pdf"; _form_pdf(p, ["Text1"])
    pdf = pikepdf.open(str(p)); props = []
    applied, deferred = RP._fix_pdf_form_fields(pdf, proposals=props, applied_fixes=[])
    assert deferred == 1 and applied == []
    assert len(props) == 1 and props[0]["kind"] == "pdf-field-name"
    assert props[0]["locator"].startswith("pdf:field:")
    assert _tus(p)["Text1"] == ""                          # nothing auto-written to the source


# ── apply-on-approval writes /TU by locator ──────────────────────────────────
def test_apply_writes_approved_name_by_locator(tmp_path):
    p = tmp_path / "a.pdf"; _form_pdf(p, ["Text1"])
    pdf = pikepdf.open(str(p)); props = []
    RP._fix_pdf_form_fields(pdf, proposals=props, applied_fixes=[])
    locator = props[0]["locator"]
    fixed, applied, unresolved = RP.apply_pdf_field_name(p.read_bytes(), {locator: "Home address"})
    assert not unresolved and len(applied) == 1
    assert _tus(fixed)["Text1"] == "Home address"


def test_unified_dispatch_routes_field_and_figure(tmp_path):
    """apply_pdf_approved routes pdf:field → /TU (pdf:fig would go to /Alt); unknown → unresolved."""
    p = tmp_path / "u.pdf"; _form_pdf(p, ["Text1"])
    pdf = pikepdf.open(str(p)); props = []
    RP._fix_pdf_form_fields(pdf, proposals=props, applied_fixes=[])
    loc = props[0]["locator"]
    fixed, applied, unresolved = RP.apply_pdf_approved(
        p.read_bytes(), {loc: "Signature date", "word/x#rId9": "office"})
    assert _tus(fixed)["Text1"] == "Signature date"
    assert unresolved == ["word/x#rId9"]


# ── /FT (role) and /V (value) — the two 4.1.2 sub-checks alongside /TU ──────────
def test_field_with_valid_type_and_name_is_clean(tmp_path):
    """A named, well-typed, non-required field trips none of the three checks."""
    p = tmp_path / "clean.pdf"; _form_pdf(p, ["First Name"])
    pdf = pikepdf.open(str(p))
    RP._collect_form_fields(pdf)[0]["/TU"] = pikepdf.String("First name")
    out = tmp_path / "clean-tu.pdf"; pdf.save(str(out)); pdf.close()
    assert OSX.pdf_form_field_checks(out) == []


def test_malformed_field_type_flagged(tmp_path):
    """A field whose /FT has been corrupted to a non-spec value has no determinable role."""
    p = tmp_path / "badtype.pdf"; _form_pdf(p, ["First Name"])
    pdf = pikepdf.open(str(p))
    fld = RP._collect_form_fields(pdf)[0]
    fld["/TU"] = pikepdf.String("First name")           # named, so only the type check should fire
    fld["/FT"] = pikepdf.Name("/Bogus")
    out = tmp_path / "badtype-2.pdf"; pdf.save(str(out)); pdf.close()
    findings = OSX.pdf_form_field_checks(out)
    assert [f["ruleId"] for f in findings] == ["PDF_FORM_NO_FIELD_TYPE"]


def test_required_field_without_value_flagged(tmp_path):
    """A required field (Ff bit 2) with no /V and no /DV has no determinable current value."""
    p = tmp_path / "req.pdf"; _form_pdf(p, ["First Name"])
    pdf = pikepdf.open(str(p))
    fld = RP._collect_form_fields(pdf)[0]
    fld["/TU"] = pikepdf.String("First name")            # named + valid type, isolate the /V check
    fld["/Ff"] = pikepdf.Integer(2)                       # Required bit
    out = tmp_path / "req-2.pdf"; pdf.save(str(out)); pdf.close()
    findings = OSX.pdf_form_field_checks(out)
    assert [f["ruleId"] for f in findings] == ["PDF_FORM_REQUIRED_NO_VALUE"]


def test_required_field_with_value_not_flagged(tmp_path):
    p = tmp_path / "reqv.pdf"; _form_pdf(p, ["First Name"])
    pdf = pikepdf.open(str(p))
    fld = RP._collect_form_fields(pdf)[0]
    fld["/TU"] = pikepdf.String("First name")
    fld["/Ff"] = pikepdf.Integer(2)
    fld["/V"] = pikepdf.String("Jane")
    out = tmp_path / "reqv-2.pdf"; pdf.save(str(out)); pdf.close()
    assert OSX.pdf_form_field_checks(out) == []


def test_optional_empty_field_not_flagged_for_value(tmp_path):
    """A non-required field with no /V is completely normal (an empty optional text box)."""
    p = tmp_path / "opt.pdf"; _form_pdf(p, ["First Name"])
    pdf = pikepdf.open(str(p))
    RP._collect_form_fields(pdf)[0]["/TU"] = pikepdf.String("First name")
    out = tmp_path / "opt-2.pdf"; pdf.save(str(out)); pdf.close()
    assert OSX.pdf_form_field_checks(out) == []
