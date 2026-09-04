"""2.5.3 Label in Name — heuristic extension to non-push-button AcroForm fields.

Covers the second check in label_in_name.detect: text fields (/Tx), checkboxes and radio
buttons (/Btn non-pushbutton), choice fields (/Ch), and signature fields (/Sig).

For these types the visible field label is separate page text not programmatically linked
to the field object, so a direct caption-to-name comparison is impossible without rendering.
Instead the accessible name (/TU, or /T as fallback) is flagged when it looks like a
developer identifier — snake_case (contains underscore) or camelCase (starts lowercase with
at least one uppercase letter). Such a name can never match what a speech-input user says.

Rule ID: PDF_ACCESSIBLE_NAME_PROGRAMMATIC
Severity: MODERATE (heuristic — could miss or misidentify edge cases)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

pikepdf = pytest.importorskip("pikepdf")

from formats.pdf.detectors.label_in_name import (  # noqa: E402
    _looks_programmatic,
    detect,
)

SPIKE = ROOT / "test-corpus" / "spike-fixtures" / "pdf-form-fields-spike.pdf"
_FLAG_PUSHBUTTON = 1 << 16
_FLAG_RADIO = 1 << 15
_RULE = "PDF_ACCESSIBLE_NAME_PROGRAMMATIC"


# ── unit: _looks_programmatic predicate ───────────────────────────────────────────────

def test_snake_case_is_programmatic():
    assert _looks_programmatic("dob_field")
    assert _looks_programmatic("full_name")
    assert _looks_programmatic("submit_btn")


def test_camel_case_starting_lower_is_programmatic():
    assert _looks_programmatic("firstName")
    assert _looks_programmatic("dateOfBirth")


def test_name_with_space_is_not_programmatic():
    assert not _looks_programmatic("Full name")
    assert not _looks_programmatic("Date of birth")
    assert not _looks_programmatic("First Name")


def test_uppercase_start_single_word_is_not_programmatic():
    """Labels like 'Name', 'Email', 'DOB' starting uppercase are plausible human labels."""
    assert not _looks_programmatic("Name")
    assert not _looks_programmatic("Email")
    assert not _looks_programmatic("DOB")


def test_single_lowercase_word_is_not_programmatic():
    """Single lowercase words ('name', 'email') are not flagged — too ambiguous."""
    assert not _looks_programmatic("name")
    assert not _looks_programmatic("email")


def test_empty_string_is_not_programmatic():
    assert not _looks_programmatic("")


# ── fixture builder helpers ────────────────────────────────────────────────────────────

def _field_dict(ft: str, t: str, tu: str | None, ff: int = 0) -> dict:
    d: dict = {"/FT": pikepdf.Name(ft), "/T": pikepdf.String(t),
                "/Rect": pikepdf.Array([10, 10, 100, 40])}
    if ff:
        d["/Ff"] = ff
    if tu is not None:
        d["/TU"] = pikepdf.String(tu)
    return d


def _form(path: Path, fields_spec: list[dict]) -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 200))
    field_objs = []
    for spec in fields_spec:
        obj = pdf.make_indirect(pikepdf.Dictionary(spec))
        field_objs.append(obj)
    pdf.pages[0].Annots = pikepdf.Array(field_objs)
    pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array(field_objs), DA=pikepdf.String("/Helv 0 Tf 0 g")))
    pdf.save(str(path))
    return path


# ── detect: text fields (/Tx) ─────────────────────────────────────────────────────────

def test_text_field_programmatic_tu_flagged(tmp_path):
    """Text field with a snake_case /TU is flagged."""
    p = _form(tmp_path / "tx_bad_tu.pdf", [
        _field_dict("/Tx", "field1", tu="dob_field"),
    ])
    results = detect(p)
    assert any(r["ruleId"] == _RULE for r in results), results


def test_text_field_no_tu_programmatic_t_flagged(tmp_path):
    """Text field with no /TU — fallback /T is snake_case → flagged."""
    p = _form(tmp_path / "tx_no_tu.pdf", [
        _field_dict("/Tx", "dob_field", tu=None),
    ])
    results = detect(p)
    assert any(r["ruleId"] == _RULE for r in results), results


def test_text_field_readable_tu_not_flagged(tmp_path):
    """Text field with human-readable /TU (has space) → not flagged."""
    p = _form(tmp_path / "tx_ok.pdf", [
        _field_dict("/Tx", "field1", tu="Full name"),
    ])
    assert detect(p) == []


def test_text_field_uppercase_start_t_not_flagged(tmp_path):
    """Text field with /T starting uppercase and no /TU → not flagged (plausible label)."""
    p = _form(tmp_path / "tx_upper.pdf", [
        _field_dict("/Tx", "Name", tu=None),
    ])
    assert detect(p) == []


# ── detect: checkbox (/Btn non-pushbutton, Ff=0) ──────────────────────────────────────

def test_checkbox_programmatic_name_flagged(tmp_path):
    """Checkbox (Ff=0) with snake_case accessible name → flagged."""
    p = _form(tmp_path / "cb_bad.pdf", [
        _field_dict("/Btn", "agree_terms", tu=None, ff=0),
    ])
    results = detect(p)
    assert any(r["ruleId"] == _RULE for r in results), results


def test_checkbox_readable_tu_not_flagged(tmp_path):
    """Checkbox (Ff=0) with human-readable /TU (has space) → not flagged."""
    p = _form(tmp_path / "cb_ok.pdf", [
        _field_dict("/Btn", "cb1", tu="Agree to terms", ff=0),
    ])
    assert detect(p) == []


# ── detect: radio button (/Btn with radio flag) ───────────────────────────────────────

def test_radio_programmatic_name_flagged(tmp_path):
    """Radio button (bit 15 set) with snake_case name → flagged."""
    p = _form(tmp_path / "radio_bad.pdf", [
        _field_dict("/Btn", "payment_method", tu=None, ff=_FLAG_RADIO),
    ])
    results = detect(p)
    assert any(r["ruleId"] == _RULE for r in results), results


def test_radio_readable_tu_not_flagged(tmp_path):
    """Radio button with human-readable /TU → not flagged."""
    p = _form(tmp_path / "radio_ok.pdf", [
        _field_dict("/Btn", "r1", tu="Payment method", ff=_FLAG_RADIO),
    ])
    assert detect(p) == []


# ── detect: choice field (/Ch) ────────────────────────────────────────────────────────

def test_choice_field_programmatic_name_flagged(tmp_path):
    """Choice field (/Ch) with camelCase name → flagged."""
    p = _form(tmp_path / "ch_bad.pdf", [
        _field_dict("/Ch", "countryCode", tu=None),
    ])
    results = detect(p)
    assert any(r["ruleId"] == _RULE for r in results), results


def test_choice_field_readable_tu_not_flagged(tmp_path):
    """Choice field with human-readable /TU → not flagged."""
    p = _form(tmp_path / "ch_ok.pdf", [
        _field_dict("/Ch", "ch1", tu="Country"),
    ])
    assert detect(p) == []


# ── finding shape ─────────────────────────────────────────────────────────────────────

def test_finding_has_correct_rule_id(tmp_path):
    p = _form(tmp_path / "f.pdf", [_field_dict("/Tx", "dob_field", tu=None)])
    results = [r for r in detect(p) if r["ruleId"] == _RULE]
    assert results, "expected exactly one PDF_ACCESSIBLE_NAME_PROGRAMMATIC finding"


def test_finding_wcag_tag(tmp_path):
    p = _form(tmp_path / "f.pdf", [_field_dict("/Tx", "dob_field", tu=None)])
    results = [r for r in detect(p) if r["ruleId"] == _RULE]
    assert results and "2.5.3" in results[0]["wcag"]


def test_finding_severity_is_moderate(tmp_path):
    p = _form(tmp_path / "f.pdf", [_field_dict("/Tx", "dob_field", tu=None)])
    results = [r for r in detect(p) if r["ruleId"] == _RULE]
    assert results and results[0]["severity"] == "MODERATE"


# ── spike fixture (structural test against a real form PDF) ───────────────────────────

@pytest.mark.skipif(not SPIKE.exists(), reason="spike fixture not present")
def test_spike_fixture_dob_field_flagged():
    """dob_field has no /TU — accessible name falls back to /T='dob_field' (snake_case) → flagged."""
    results = detect(SPIKE)
    programmatic = [r for r in results if r["ruleId"] == _RULE]
    assert programmatic, (
        "expected PDF_ACCESSIBLE_NAME_PROGRAMMATIC for dob_field; got: " + str(results)
    )
    assert any("dob_field" in r["detail"] for r in programmatic), (
        "detail should name the offending field; got: " + str(programmatic)
    )


@pytest.mark.skipif(not SPIKE.exists(), reason="spike fixture not present")
def test_spike_fixture_full_name_not_flagged():
    """full_name has /TU='Full name' (has space) → not programmatic → no heuristic finding."""
    results = detect(SPIKE)
    programmatic = [r for r in results if r["ruleId"] == _RULE]
    for r in programmatic:
        assert "full_name" not in r.get("detail", ""), (
            "full_name should not be flagged because its TU='Full name' has a space"
        )


# ── bite checks (dependency verification) ────────────────────────────────────────────

def test_snake_case_bite_check():
    """Break the predicate: verify the test would fail if _looks_programmatic('dob_field') = False."""
    assert _looks_programmatic("dob_field"), (
        "bite check: _looks_programmatic must return True for 'dob_field'; "
        "if this fails the dependency above is not real"
    )


def test_camelCase_bite_check():
    assert _looks_programmatic("dateOfBirth"), (
        "bite check: _looks_programmatic must return True for 'dateOfBirth'"
    )


# ── regression: push-button check still works ─────────────────────────────────────────

def test_push_button_detection_not_broken(tmp_path):
    """Extending to non-button fields must not break the existing push-button check."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 200))
    btn = pdf.make_indirect(pikepdf.Dictionary({
        "/FT": pikepdf.Name("/Btn"),
        "/Ff": _FLAG_PUSHBUTTON,
        "/T": pikepdf.String("btn1"),
        "/TU": pikepdf.String("btn_primary"),
        "/MK": pikepdf.Dictionary(CA=pikepdf.String("Go")),
        "/Rect": pikepdf.Array([10, 10, 100, 40]),
    }))
    pdf.pages[0].Annots = pikepdf.Array([btn])
    pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([btn]), DA=pikepdf.String("/Helv 0 Tf 0 g")))
    path = tmp_path / "pushbtn_fail.pdf"
    pdf.save(str(path))
    results = detect(path)
    assert any(r["ruleId"] == "PDF_LABEL_NOT_IN_NAME" for r in results), results
