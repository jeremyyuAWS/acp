"""Tests for the docx form-field LABEL proposer (api/propose_forms.py).

The deterministic path (adjacent-prompt derivation) is pure and exercised directly. The
model-backed fallback is tested with api.ai stubbed so no Ollama is required — same posture as
the other proposer tests. Fixtures are hand-built zip/XML, mirroring test_office_structure.py's
_docx() helper (python-docx isn't a declared dependency).
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402
import propose_forms as PF  # noqa: E402

_DOC = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')


def _para(*runs: str, sdt: str = "") -> str:
    text = "".join(f"<w:r><w:t>{r}</w:t></w:r>" for r in runs)
    return f"<w:p>{text}{sdt}</w:p>"


def _sdt(field: str, *, alias: str | None = None, sid: str = "1", content: str = "[ ]") -> str:
    a = f'<w:alias w:val="{alias}"/>' if alias is not None else ""
    return (f"<w:sdt><w:sdtPr>{a}<w:id w:val=\"{sid}\"/>{field}</w:sdtPr>"
            f"<w:sdtContent><w:r><w:t>{content}</w:t></w:r></w:sdtContent></w:sdt>")


def _docx(tmp: Path, body: str) -> Path:
    p = tmp / "form.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", _DOC.format(body=body))
    return p


# ── Deterministic derivation from adjacent prompt text ────────────────────────

def test_inline_label_before_checkbox():
    body = _para("Full name:", sdt=_sdt("<w:checkbox/>"))
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert len(props) == 1
    p = props[0]
    assert p["proposed_value"] == "Full name"          # trailing colon stripped
    assert p["source"] == "derived from adjacent label text (deterministic)"
    # The locator is STRUCTURAL (w:id), so an applier can resolve it back to this exact
    # control; the reader-facing noun moved to the rationale, which is where a reviewer
    # actually reads it. An ordinal-or-prose locator addressed the wrong field once any
    # earlier control changed.
    assert p["locator"] == "docx:sdt:1"
    assert "checkbox" in p["rationale"]
    assert p["before"] == "[ ]"


def test_stacked_label_in_previous_paragraph():
    body = _para("Date of birth") + _para(sdt=_sdt("<w:date/>", sid="7"))
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert len(props) == 1
    assert props[0]["proposed_value"] == "Date of birth"
    assert props[0]["locator"] == "docx:sdt:7"
    assert "date picker" in props[0]["rationale"]


def test_table_left_cell_label():
    # A two-cell row: label cell, then the field's own cell (field opens its own paragraph).
    body = ("<w:tbl><w:tr>"
            "<w:tc><w:p><w:r><w:t>Email address</w:t></w:r></w:p></w:tc>"
            f"<w:tc>{_para(sdt=_sdt('<w:comboBox/>'))}</w:tc>"
            "</w:tr></w:tbl>")
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert len(props) == 1
    assert props[0]["proposed_value"] == "Email address"
    assert props[0]["locator"] == "docx:sdt:1"
    assert "combo box" in props[0]["rationale"]


def test_required_asterisk_and_enumerator_stripped():
    body = _para("3. Preferred contact method: *", sdt=_sdt("<w:dropDownList/>"))
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert props[0]["proposed_value"] == "Preferred contact method"


def test_trailing_clause_only_from_long_prose():
    body = _para("Please read the instructions carefully before you begin. Home address:",
                 sdt=_sdt("<w:checkbox/>"))
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert props[0]["proposed_value"] == "Home address"


# ── Guards / lock-step with the detector (mutation-check the skips) ───────────

def test_already_labeled_field_yields_no_proposal():
    body = _para("Full name:", sdt=_sdt("<w:checkbox/>", alias="Agree to terms"))
    assert PF.proposals_from_document_xml(_DOC.format(body=body)) == []


def test_empty_alias_is_still_unlabeled():
    # Mirrors the detector: an empty alias counts as no label.
    body = _para("Full name:", sdt=_sdt("<w:checkbox/>", alias=""))
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert len(props) == 1 and props[0]["proposed_value"] == "Full name"


def test_non_input_content_control_is_ignored():
    # A TOC/rich-text sdt is not an interactive input gallery type — no proposal, matching
    # office_structure (which also passes it).
    toc = ("<w:sdt><w:sdtPr><w:id w:val=\"2\"/>"
           "<w:docPartObj><w:docPartGallery w:val=\"Table of Contents\"/></w:docPartObj>"
           "</w:sdtPr><w:sdtContent><w:r><w:t>Contents...</w:t></w:r></w:sdtContent></w:sdt>")
    body = _para("Heading") + toc
    assert PF.proposals_from_document_xml(_DOC.format(body=body)) == []


def test_proposal_covers_exactly_what_detector_flags():
    # Lock-step: one unlabeled input field flagged → one proposal.
    body = _para("City:", sdt=_sdt("<w:checkbox/>"))
    tmp = Path(__file__).resolve().parent
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = _docx(Path(d), body)
        findings = [f for f in os_.docx_checks(path)
                    if f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL"]
        props = PF.form_field_proposals(path)
    assert len(findings) == 1
    assert len(props) == 1 and props[0]["proposed_value"] == "City"


def test_no_usable_label_and_no_model_yields_nothing():
    # No adjacent prompt, model disabled → no proposal (stays a plain HITL deferral).
    body = _para(sdt=_sdt("<w:checkbox/>"))
    assert PF.proposals_from_document_xml(_DOC.format(body=body), ai_enabled=False) == []


# ── Local-model fallback (api.ai stubbed — no Ollama needed) ──────────────────

def test_model_fallback_when_no_adjacent_label(monkeypatch):
    import ai as _ai
    monkeypatch.setattr(_ai, "is_available", lambda: True)
    monkeypatch.setattr(_ai, "suggest_fix",
                        lambda *a, **k: {"suggestion": "Signature", "model": "llama-test"})
    # Field alone in its paragraph, some prose after it for context.
    body = _para(sdt=_sdt("<w:checkbox/>")) + _para("Sign here to authorize the transfer.")
    props = PF.proposals_from_document_xml(_DOC.format(body=body), ai_enabled=True)
    assert len(props) == 1
    p = props[0]
    assert p["proposed_value"] == "Signature"
    assert "AI text model (llama-test)" in p["source"]
    assert "human judgement required" in p["source"]


def test_model_off_switch_skips_model(monkeypatch):
    import ai as _ai
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return {"suggestion": "X", "model": "m"}

    monkeypatch.setattr(_ai, "is_available", lambda: True)
    monkeypatch.setattr(_ai, "suggest_fix", _boom)
    body = _para(sdt=_sdt("<w:checkbox/>")) + _para("Some later text.")
    assert PF.proposals_from_document_xml(_DOC.format(body=body), ai_enabled=False) == []
    assert called["n"] == 0                              # model never consulted when off


def test_model_reject_non_label_output(monkeypatch):
    import ai as _ai
    monkeypatch.setattr(_ai, "is_available", lambda: True)
    # A rambling model response is not label-shaped → rejected, no proposal.
    monkeypatch.setattr(_ai, "suggest_fix", lambda *a, **k: {
        "suggestion": "You should add a descriptive title to this control so that "
                      "assistive technology can announce it to the user clearly", "model": "m"})
    body = _para(sdt=_sdt("<w:checkbox/>")) + _para("Later text.")
    assert PF.proposals_from_document_xml(_DOC.format(body=body), ai_enabled=True) == []


# ── Robustness ────────────────────────────────────────────────────────────────

def test_form_field_proposals_bad_zip_returns_empty(tmp_path):
    junk = tmp_path / "not.docx"
    junk.write_bytes(b"not a zip")
    assert PF.form_field_proposals(junk) == []


def test_multiple_fields_document_order():
    body = (_para("First name:", sdt=_sdt("<w:checkbox/>", sid="1"))
            + _para("Last name:", sdt=_sdt("<w:checkbox/>", sid="2")))
    props = PF.proposals_from_document_xml(_DOC.format(body=body))
    assert [p["proposed_value"] for p in props] == ["First name", "Last name"]
