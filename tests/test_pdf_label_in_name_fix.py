"""2.5.3 Label in Name on .pdf — the deterministic lane, verified against the real detector.

WHY THIS FILE EXISTS. `remediation_capability` used to say, in its own comment,
`"2.5.3": HUMAN,  # ... no write-back built yet` — while the SAME criterion on html has been
⚡ auto for as long as `remediate._fix_label_in_name` has existed. The detector already extracted
both strings the fix needs (the visible caption from `/MK /CA`, the accessible name from `/TU` or
`/T`) and had nowhere to send them. Nothing was missing but the write.

WHY IT IS ⚡ AND NOT 🤖, which is the claim most worth testing. The 4.1.2 fixer beside it must
decide what a field should be CALLED, and when `/T` is a generic auto-name there is no honest
machine answer, so it defers to a human. 2.5.3 asks a strictly narrower question whose answer is
already in the file: the accessible name must CONTAIN the visible label, and the visible label is
sitting in `/MK /CA`. Nothing is invented, so nothing needs approving.

WHAT KEEPS IT HONEST. Three abstentions, each its own test below and none an edge case:
  * a button whose name ALREADY contains its caption is not touched — the fixer must repair
    exactly what the detector reports and not edit documents over a rule nobody stated;
  * a button with no caption has nothing to align to and is left alone;
  * `/T` is NEVER rewritten. It is the key form data is submitted under and scripts address
    fields by, so "fixing" a label through it would corrupt the form while reporting success —
    the same lesson `apply_field_name.py` records as w:alias-not-w:tag.

AND THE ASSESSMENT AXIS MUST NOT MOVE. `_assessment()` derives 🟢 from ⚡, so flipping the lane
without an ASSESSMENT_OVERRIDES entry would have started certifying Label in Name on PDFs — a
false PASS, and one no amount of fixer testing would catch, because the fixer genuinely works.
`test_the_lane_flip_did_not_start_certifying_the_criterion` is the load-bearing test in this
file.

Every assertion runs the real detector before and after the real fixer. A fixer that believes it
succeeded is not evidence; the detector going quiet is.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pikepdf = pytest.importorskip("pikepdf")

import remediate_pdf  # noqa: E402
import remediation_capability as rc  # noqa: E402
from formats.pdf.detectors import label_in_name  # noqa: E402

_FLAG_PUSHBUTTON = 1 << 16          # Ff bit 17 (ISO 32000 Table 227), 0-indexed
_FLAG_RADIO = 1 << 15


def _button(pdf, *, name, caption=None, tooltip=None, rect, pushbutton=True, ft="/Btn"):
    d = pikepdf.Dictionary(
        Type=pikepdf.Name("/Annot"), Subtype=pikepdf.Name("/Widget"),
        FT=pikepdf.Name(ft), Ff=(_FLAG_PUSHBUTTON if pushbutton else 0),
        T=pikepdf.String(name), Rect=pikepdf.Array([*rect]), F=4)
    if caption is not None:
        d["/MK"] = pikepdf.Dictionary(CA=pikepdf.String(caption))
    if tooltip is not None:
        d["/TU"] = pikepdf.String(tooltip)
    return pdf.make_indirect(d)


def _form(tmp_path, fields, filename="form.pdf") -> Path:
    """A real AcroForm PDF. Built rather than fixtured because the whole point is to exercise
    pikepdf's own reading of the structure the fixer writes."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    annots = [_button(pdf, rect=(50, 700 - i * 40, 150, 730 - i * 40), **f)
              for i, f in enumerate(fields)]
    page.obj["/Annots"] = pdf.make_indirect(pikepdf.Array(annots))
    pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array(annots), DA=pikepdf.String("/Helv 0 Tf 0 g")))
    out = tmp_path / filename
    pdf.save(str(out))
    return out


def _fields(path: Path) -> list[dict]:
    """Every field as {T, caption, TU} — what a reader would see, not pikepdf objects."""
    with pikepdf.open(str(path)) as pdf:
        rows = []
        for f in pdf.Root["/AcroForm"]["/Fields"]:
            mk = f.get("/MK")
            rows.append({
                "T": str(f.get("/T", "")),
                "caption": (str(mk.get("/CA")) if mk is not None and mk.get("/CA") is not None
                            else None),
                "TU": (str(f.get("/TU")) if f.get("/TU") is not None else None),
            })
        return rows


def _fix_only(path: Path) -> Path:
    """Run ONLY the 2.5.3 pass, in place. Isolates this fixer from the rest of the pipeline so a
    test about label-in-name cannot be quietly satisfied by the 4.1.2 pass beside it — which, as
    test_the_412_pass_can_create_the_failure below shows, really can change the same key."""
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        remediate_pdf._fix_pdf_label_in_name(pdf)
        pdf.save(str(path))
    return path


# ── the fixture itself fails, before anything is claimed about fixing it ─────────────────────

def test_the_fixture_really_does_fail_the_criterion(tmp_path):
    """Run first and asserted on its own: every test below is "the detector goes quiet", which a
    fixture that never spoke would satisfy for free."""
    p = _form(tmp_path, [dict(name="btn_primary", caption="Submit", tooltip="btn_primary")])
    findings = label_in_name.detect(p)
    assert len(findings) == 1
    assert findings[0]["ruleId"] == "PDF_LABEL_NOT_IN_NAME"
    assert 'caption "Submit" not in name "btn_primary"' in findings[0]["detail"]


# ── the round trip ───────────────────────────────────────────────────────────────────────────

def test_the_fix_silences_the_detector(tmp_path):
    p = _form(tmp_path, [
        dict(name="btn_primary", caption="Submit", tooltip="btn_primary"),
        dict(name="search", caption="Go", tooltip="Search the form"),
    ])
    assert label_in_name.detect(p)
    assert label_in_name.detect(_fix_only(p)) == []


def test_the_visible_label_comes_first_and_the_authors_tooltip_survives(tmp_path):
    """Mirrors html 2.5.3 exactly (`f"{visible} — {old}"`). Both halves matter: leading with the
    visible label is what speech input matches on, and discarding the author's tooltip would
    silence the finding by throwing away the sentence a screen-reader user actually hears."""
    p = _form(tmp_path, [dict(name="search", caption="Go", tooltip="Search the form")])
    _fix_only(p)
    assert _fields(p)[0]["TU"] == "Go — Search the form"


def test_a_button_with_no_tooltip_gains_one_rather_than_having_its_T_rewritten(tmp_path):
    """The detector compares against /T when /TU is absent, so a bare button can fail with no /TU
    to edit. The repair is to ADD one — never to rewrite /T, which is the key the form's data is
    submitted under."""
    p = _form(tmp_path, [dict(name="b1", caption="Continue")])
    _fix_only(p)
    row = _fields(p)[0]
    assert row["TU"] == "Continue"
    assert row["T"] == "b1", "/T was rewritten — that changes what the form submits"
    assert label_in_name.detect(p) == []


def test_no_field_T_is_ever_modified(tmp_path):
    p = _form(tmp_path, [
        dict(name="btn_primary", caption="Submit", tooltip="btn_primary"),
        dict(name="search", caption="Go", tooltip="Search the form"),
        dict(name="b3", caption="Continue"),
    ])
    before = [r["T"] for r in _fields(p)]
    _fix_only(p)
    assert [r["T"] for r in _fields(p)] == before


# ── the abstentions ──────────────────────────────────────────────────────────────────────────

def test_a_button_that_already_passes_is_left_exactly_alone(tmp_path):
    """The fixer must repair what the detector reports and nothing else. Rewriting a passing
    field would be editing a customer's document over a rule nobody stated — and it would show up
    in the remediation diff as a change with no finding behind it."""
    p = _form(tmp_path, [
        dict(name="x1", caption="Save", tooltip="Save the draft"),   # name contains the caption
        dict(name="Print this page", caption="Print"),               # passes via /T, no /TU
    ])
    assert label_in_name.detect(p) == []
    before = _fields(p)
    _fix_only(p)
    assert _fields(p) == before


def test_a_button_with_no_visible_caption_is_left_alone(tmp_path):
    """No /MK /CA means nothing is displayed on the button face, so there is no visible label for
    a name to contain. Inventing one from /T would be the 4.1.2 fixer's job, not this one's."""
    p = _form(tmp_path, [dict(name="mystery", tooltip="does something")])
    before = _fields(p)
    _fix_only(p)
    assert _fields(p) == before


def test_non_pushbutton_fields_are_left_alone(tmp_path):
    """A checkbox or text field displays its label as a separate text object drawn on the page,
    with no reference to the field object — so there is no caption to compare and the criterion
    cannot be judged for it. This is the same boundary the detector draws and the reason the
    assessment axis stays 🟡; a fixer that reached past it would be guessing."""
    p = _form(tmp_path, [
        dict(name="agree", caption="I agree", tooltip="chk1", pushbutton=False),   # checkbox
        dict(name="email", caption="Email", tooltip="txt1", ft="/Tx"),             # text field
    ])
    before = _fields(p)
    _fix_only(p)
    assert _fields(p) == before


def test_a_file_that_is_not_a_form_is_a_no_op(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    p = tmp_path / "plain.pdf"
    pdf.save(str(p))
    with pikepdf.open(str(p), allow_overwriting_input=True) as opened:
        assert remediate_pdf._fix_pdf_label_in_name(opened) == []


# ── the interaction with 4.1.2, which runs first over the same key ───────────────────────────

def test_the_412_pass_can_create_the_failure_and_this_pass_repairs_it(tmp_path):
    """The reason the 2.5.3 pass is ordered AFTER the 4.1.2 one, verified rather than asserted in
    a comment.

    A push button whose /T is meaningful ("dispatch_order") but whose caption is a short verb
    ("Send") is named by the 4.1.2 fixer as "Dispatch Order" — a correct 4.1.2 fix that leaves the
    accessible name not containing the visible label, i.e. a 2.5.3 failure ACP introduced itself.
    Running second, this pass sees that output and repairs it; running first it would have been
    overwritten.
    """
    p = _form(tmp_path, [dict(name="dispatch_order", caption="Send")])

    # 4.1.2 alone: names the field correctly, and 2.5.3 still fails.
    only_412 = tmp_path / "only412.pdf"
    shutil.copy(p, only_412)
    with pikepdf.open(str(only_412), allow_overwriting_input=True) as pdf:
        remediate_pdf._fix_pdf_form_fields(pdf)
        pdf.save(str(only_412))
    assert _fields(only_412)[0]["TU"] == "Dispatch Order"
    assert label_in_name.detect(only_412), "the premise is gone — 4.1.2 no longer creates this"

    # The real pipeline, both passes in order.
    both = tmp_path / "both.pdf"
    shutil.copy(p, both)
    fixed, applied, _skipped = remediate_pdf.remediate_pdf(both, ai_enabled=False)
    target = Path(fixed) if fixed else both
    assert _fields(target)[0]["TU"] == "Send — Dispatch Order"
    assert label_in_name.detect(target) == []
    assert any("2.5.3" in m for m in applied)
    assert any("4.1.2" in m for m in applied), "both fixes should be reported, not just the last"


def test_the_pipeline_records_a_diff_a_reader_can_check(tmp_path):
    """The remediation diff is what the certification report shows. A fix with no before/after row
    is invisible to everyone downstream of the worker."""
    p = _form(tmp_path, [dict(name="btn_primary", caption="Submit", tooltip="btn_primary")])
    diffs: list[dict] = []
    remediate_pdf.remediate_pdf(p, diffs=diffs, ai_enabled=False)
    rows = [d for d in diffs if d.get("rule_id") == "2.5.3"]
    assert len(rows) == 1
    assert rows[0]["before"] == "btn_primary"
    assert rows[0]["after"] == "Submit — btn_primary"


def test_the_criterion_can_be_scoped_out(tmp_path):
    """`in_scope` is the operator's selection — a PREDICATE, not a set (see remediate_pdf._sc_ok;
    passing a set here raised TypeError on the first run of this test). A criterion they excluded
    must not be silently fixed anyway: every other pass in remediate_pdf honours this and so must
    this one."""
    p = _form(tmp_path, [dict(name="btn_primary", caption="Submit", tooltip="btn_primary")])
    before = _fields(p)
    remediate_pdf.remediate_pdf(p, ai_enabled=False, in_scope=lambda sc: sc != "2.5.3")
    assert _fields(p) == before, "a criterion the operator excluded was fixed anyway"


# ── the axis guard, which is the point of the whole exercise ─────────────────────────────────

def test_the_remediation_lane_says_auto():
    assert rc.REMEDIATION["pdf"]["2.5.3"] == rc.AUTO


def test_the_lane_flip_did_not_start_certifying_the_criterion():
    """THE load-bearing test. `_assessment()` derives 🟢 auto from ⚡ auto, so moving the lane
    without an ASSESSMENT_OVERRIDES entry would have made a clean PDF scan certify 2.5.3 — a false
    PASS, and one every other test in this file would still have passed, because the fixer works.

    What the fix proves is that every PUSH BUTTON's name contains its caption. 2.5.3 covers every
    labelled control, and a form whose text inputs are all unlabelled scans clean while failing
    the criterion outright. The registry says the same on its own axis (label_in_name registers
    PARTIAL — "only push buttons carry a caption in the AcroForm dictionary"); this keeps the two
    from disagreeing.
    """
    assert rc.assessment_lane("pdf", "2.5.3") == rc.A_REVIEW
    assert ("pdf", "2.5.3") in rc.ASSESSMENT_OVERRIDES


def test_html_stays_the_model_this_was_copied_from():
    """html 2.5.3 is ⚡ AND 🟢 — its detector reads the visible text of every link and button, so a
    clean scan really does cover the criterion there. The asymmetry with pdf is the honest part,
    not an inconsistency to tidy away."""
    assert rc.REMEDIATION["html"]["2.5.3"] == rc.AUTO
    assert rc.assessment_lane("html", "2.5.3") == rc.A_AUTO


# ── the dispatch this change wired ───────────────────────────────────────────────────────────

def test_2_5_3_on_pdf_is_dispatched_now():
    """2.5.3 on pdf was REGISTERED and never CALLED.

    Every registry-backed detector gets a thin wrapper in office_structure.py that checks_for()
    invokes; this pair had neither, so it was printed in the capability matrix and in
    docs/TODO.md's generated coverage table as PARTIAL/HIGH while no scan of any PDF had ever
    produced a 2.5.3 finding. A missing detector reads as a gap, which is honest; a declared one
    that never runs reads as a clean result, which is the "unsupported must never read as passed"
    rule broken in the direction nobody notices.

    Pinned at the dispatch site rather than by scanning a fixture here, because the fixture proof
    already exists one layer up: tests/test_remediation_capability.py::test_pdf_auto_entries_clear
    builds a PDF with a failing push button and asserts 2.5.3 both fires and clears. That test
    needs the analysis engines and skips in a bare container; this one does not, so the wiring
    stays pinned wherever the suite runs.
    """
    from office_structure import pdf_label_in_name_checks  # noqa: F401
    src = (Path(__file__).resolve().parent.parent / "api" / "office_structure.py").read_text()
    dispatch = src.split('if ext == ".pdf":', 1)[1].split("if ext ==", 1)[0]
    assert "pdf_label_in_name_checks(path)" in dispatch, (
        "the wrapper exists but checks_for's .pdf branch does not call it — which is exactly the "
        "state 2.5.3 was in")
