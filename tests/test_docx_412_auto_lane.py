"""4.1.2 Name, Role, Value on .docx — the deterministic lane, verified against the real detector.

WHY THIS FILE EXISTS. The lane table now calls docx 4.1.2 ⚡ auto. That claim is only worth
making if the write actually silences the detector, so these tests run
`formats/docx/detectors/name_role_value.detect` itself before and after the fix rather than
asserting on the fixer's own report of what it did. A fixer that believes it succeeded is not
evidence; the detector going quiet is.

WHAT THE LANE IS. `form_labels.adjacent_label` borrows a field's label from adjacent VISIBLE
text — an inline caption, the preceding table cell, or a preceding paragraph that reads like a
label — and writes it into `<w:alias>`. That one attribute is simultaneously the visible prompt
3.3.2 asks for and the accessible NAME 4.1.2 asks for, which is why one write settles both.

WHAT KEEPS IT HONEST, and the reason it is ⚡ rather than a guess: a field with NO adjacent text
is never named. It stays a finding and routes to review. That abstention is the whole basis of
the auto claim — a borrowed label is a mechanical restatement of text already in the document,
whereas an invented one would silence the detector while leaving the field anonymous to a screen
reader. Same asymmetry as a wrong alt on an image: the failure mode is invisible, because the
check that would have caught it is the one the wrong value suppresses. `test_bare_field_*` below
is therefore the load-bearing test in this file, not an edge case.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

etree = pytest.importorskip("lxml.etree")

import form_labels as fl  # noqa: E402
from formats.docx.detectors import name_role_value as nrv  # noqa: E402

_DOC = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>{body}</w:body></w:document>")


def _sdt(kind: str, *, alias: str | None = None) -> str:
    alias_xml = f'<w:alias w:val="{alias}"/>' if alias is not None else ""
    return (f"<w:sdt><w:sdtPr>{alias_xml}<w:{kind}/></w:sdtPr>"
            "<w:sdtContent><w:r><w:t> </w:t></w:r></w:sdtContent></w:sdt>")


def _run(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def _root(body: str):
    return etree.fromstring(_DOC.format(body=body).encode("utf-8"))


def _detect_412(root, tmp_path) -> list[dict]:
    """Serialize the tree and run the REAL 4.1.2 detector over it."""
    doc = tmp_path / "d.docx"
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr("word/document.xml", etree.tostring(root))
    return nrv.detect(doc)


def _fix(root) -> list[tuple[object, str]]:
    """Apply the deterministic lane exactly as remediate_office does."""
    labelled, _bare = fl.plan_labels(root)
    for sdt, label in labelled:
        fl.set_alias(sdt, label)
    return labelled


# ── the lane clears the criterion, measured on the detector ──────────────────

@pytest.mark.parametrize("case,body,expected_name", [
    ("inline caption",
     "<w:p>" + _run("Date of birth:") + _sdt("date") + "</w:p>",
     "Date of birth"),
    ("table cell label",
     "<w:tbl><w:tr><w:tc><w:p>" + _run("Full name") + "</w:p></w:tc>"
     "<w:tc><w:p>" + _sdt("comboBox") + "</w:p></w:tc></w:tr></w:tbl>",
     "Full name"),
    ("label on its own line",
     "<w:p>" + _run("Policy number:") + "</w:p><w:p>" + _sdt("dropDownList") + "</w:p>",
     "Policy number"),
])
def test_grounded_label_clears_412(case, body, expected_name, tmp_path):
    root = _root(body)
    assert len(_detect_412(root, tmp_path)) == 1, f"{case}: detector should fire before the fix"

    labelled = _fix(root)

    assert [lab for _el, lab in labelled] == [expected_name], (
        f"{case}: the borrowed name must be the document's own adjacent text, verbatim")
    assert _detect_412(root, tmp_path) == [], (
        f"{case}: 4.1.2 must be silent after the deterministic write — if this fails, the ⚡ lane "
        "in remediation_capability.REMEDIATION['docx']['4.1.2'] is claiming a clearance it does "
        "not deliver")


# ── the abstention that earns the auto claim ─────────────────────────────────

def test_bare_field_is_not_named_and_still_fails(tmp_path):
    """No adjacent text -> no name invented -> 4.1.2 STILL FAILS. This is the point.

    The tempting bug is to fall back to something generic ("Checkbox", the w:tag, the gallery
    type) so the fixer reports a higher clear rate. That would silence this detector while
    leaving the control anonymous to assistive technology — converting a visible failure into an
    invisible one, and making every downstream number a lie in the direction nobody audits.
    """
    root = _root("<w:p>" + _sdt("checkbox") + "</w:p>")
    assert len(_detect_412(root, tmp_path)) == 1

    labelled, bare = fl.plan_labels(root)

    assert labelled == [], "a bare field must never be auto-named"
    assert bare == 1, "it must be counted as routed-to-review, not silently dropped"
    assert len(_detect_412(root, tmp_path)) == 1, (
        "4.1.2 must still fail for a field ACP could not honestly name")


def test_author_supplied_name_is_never_overwritten(tmp_path):
    """A named field is not a finding, and the author's wording outranks a borrowed caption."""
    body = "<w:p>" + _run("Surname:") + _sdt("date", alias="Date of admission") + "</w:p>"
    root = _root(body)
    assert _detect_412(root, tmp_path) == []

    assert _fix(root) == []
    assert fl.current_alias(next(root.iter(f"{{{fl.W}}}sdt"))) == "Date of admission"


# ── scope: the criterion that is in scope is the one that gates the fixer ────

def test_412_alone_in_scope_still_runs_the_fixer():
    """A scan scoped to 4.1.2 but NOT 3.3.2 must still fix the fields.

    Before this lane was declared the gate read `_sc_ok(in_scope, "3.3.2")` alone, so scoping a
    run to 4.1.2 skipped a deterministic fix that was in scope and available — ACP left the bytes
    alone on a criterion the operator had explicitly asked about.
    """
    import remediate_office as R

    only_412 = {"4.1.2"}.__contains__
    only_332 = {"3.3.2"}.__contains__
    neither = {"1.3.1"}.__contains__

    assert R._sc_ok(only_412, "3.3.2") or R._sc_ok(only_412, "4.1.2")
    assert R._sc_ok(only_332, "3.3.2") or R._sc_ok(only_332, "4.1.2")
    assert not (R._sc_ok(neither, "3.3.2") or R._sc_ok(neither, "4.1.2"))


# ── the two axes must not be conflated ───────────────────────────────────────

def test_remediation_is_auto_but_assessment_stays_review():
    """⚡ to fix, 🟡 to assess — and the second must not follow from the first.

    `_assessment` derives 🟢 from an AUTO lane, so this pair is only correct because an explicit
    override holds the assessment axis at review. Without it, declaring the fixer would have
    silently started CERTIFYING 4.1.2 on a detector that reads content controls and nothing else
    — ActiveX controls and embedded OLE objects carry their name and role in code no static read
    can see. A clean re-scan proves the fields are named, not that the criterion is met.
    """
    import remediation_capability as rc

    assert rc.CAPABILITY["docx"]["4.1.2"]["remediation"] == rc.AUTO
    assert rc.CAPABILITY["docx"]["4.1.2"]["assessment"] == rc.A_REVIEW
    assert ("docx", "4.1.2") in rc.ASSESSMENT_OVERRIDES, (
        "the override is what stops the AUTO lane deriving a certifiable cell — deleting it is "
        "a false-PASS change, not a cleanup")


def test_opaque_controls_still_route_to_review(tmp_path):
    """ActiveX/OLE keep their 4.1.2 advisory; content controls do not get one.

    This is the escalation half of the lane. The advisory must fire for control kinds nothing can
    judge statically and must NOT fire for content controls — an advisory names its SC, so one
    emitted for a field ACP just named would permanently outvote the precise check and stop a
    correctly-named document ever clearing.
    """
    import office_structure as os_

    def _pkg(extra: dict[str, str]):
        p = tmp_path / f"c{len(extra)}{abs(hash(tuple(extra))) % 997}.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml",
                       _DOC.format(body="<w:p>" + _sdt("checkbox", alias="Consent given")
                                        + "</w:p>"))
            for n, v in extra.items():
                z.writestr(n, v)
        return p

    def _412(path):
        return [f for f in os_.office_control_review_checks(path, ".docx")
                if f["ruleId"] == "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE"]

    # A named content control is judged precisely — no advisory, so the lane's clearance stands.
    assert _412(_pkg({})) == [], (
        "an advisory for content controls would outvote the precise check and stop a correctly "
        "named document ever clearing 4.1.2")

    # An opaque control is judged by nobody — the advisory is the escalation, and must fire.
    assert len(_412(_pkg({"word/activeX/activeX1.xml": "<ax/>"}))) == 1

    # THE DOTTED EXTENSION IS LOAD-BEARING, and I had the failure mode backwards when I wrote
    # this. `_NAME_ROLE_PROVEN` is keyed ".docx", so I expected an undotted "docx" to lose the
    # proven set and OVER-fire the advisory on content controls. It does something quieter and
    # worse: `office_interactive_controls` gates on the dotted form first, so an undotted ext
    # finds no controls at all and the function returns [] — BOTH advisories vanish, 2.1.2 as
    # well as 4.1.2. Silent under-reporting, on the two criteria whose only signal this is.
    #
    # Pinned as behaviour rather than as a table lookup, because that is the shape a future
    # caller gets wrong, and nothing about it raises.
    ax = _pkg({"word/activeX/activeX1.xml": "<ax/>"})
    assert len(os_.office_control_review_checks(ax, ".docx")) == 2      # 2.1.2 + 4.1.2
    assert os_.office_control_review_checks(ax, "docx") == [], (
        "documents the trap: an undotted ext silently drops every control finding. If this "
        "starts returning findings because the lookup was made extension-normalising, delete "
        "the assertion — the trap is gone, which is strictly better.")
