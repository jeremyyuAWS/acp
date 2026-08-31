"""A deterministic predicate is not a correct one: pdf 2.5.3's containment check false-positives.

WHY THIS FILE EXISTS. `tests/test_input_purpose_precision.py` measured the 1.3.5 heuristic and,
in passing, claimed the third uninvoked detector needed no such measurement:

    "pdf 2.5.3 (`label_in_name`) is NOT a heuristic ... Its limit is which fields it can see,
     not how often it is wrong. It has no false-positive rate to measure."

That was wrong, and the reasoning behind it was the interesting part: the detector's registration
declares PARTIAL coverage with HIGH confidence, and its own docstring says the comparison "is
exact and deterministic". Both are true. Neither is evidence of correctness. A predicate can
compute the same answer every time and still be answering a different question from the one WCAG
2.5.3 asks — through applicability (which controls are in scope), accessible-name precedence
(which string is the name), or TEXT NORMALIZATION (whether two strings that read identically
compare equal). "HIGH confidence" is a declaration in a registration, not a measurement.

WHAT WAS MEASURED. The predicate is `cap.lower() in name.lower()` — a raw substring test after
case folding and nothing else. Run over nine realistic (caption, accessible name) pairs:

    Submit        / Submit the application form   pass   correct
    Go            / btn_primary_47                fail   correct — a genuine 2.5.3 failure
    Save          / save                          pass   correct — case folding works
    Don't Save    / Don't Save changes            FAIL   FALSE POSITIVE  curly vs straight quote
    Save<NBSP>File/ Save File now                 FAIL   FALSE POSITIVE  non-breaking space
    Next  Step    / Next Step of 3                FAIL   FALSE POSITIVE  doubled space
    Search<ZWSP>  / Search the catalogue          FAIL   FALSE POSITIVE  zero-width space
    Resume (NFD)  / Resume (NFC) upload           FAIL   FALSE POSITIVE  accent normalization
    Print<SHY> Pre/ Print Preview                 FAIL   FALSE POSITIVE  soft hyphen

    6 false positives out of 9.

None of these is exotic. Word and InDesign emit typographic apostrophes by default; non-breaking
spaces and soft hyphens are ordinary justification artefacts; NFD accents arrive from macOS
filesystems routinely. Every one is a button a speech-input user could operate perfectly, that
this detector would report as a SERIOUS failure.

SAME CAVEAT AS THE 1.3.5 FILE, stated because the mistake there was mine too: nine hand-built
pairs are a demonstration that the failure mode is real and reachable, NOT an estimated
production false-positive rate. The proportion of real PDFs whose captions carry a curly
apostrophe is not measured anywhere and is not claimed here.

REAL SCAN DISPATCH, AND WHAT IT FOUND. The second half of this file builds real AcroForm PDFs
and calls the detector's own entry point, with positive and negative controls. Two results:

  * the normalization false positives reproduce end to end — they are not an artefact of testing
    the predicate in isolation;
  * the two applicability risks previously recorded as UNMEASURED are both real. A push button
    whose /MK or /Ff sits on its widget annotation rather than on the merged field dictionary is
    invisible to the detector, and that is the ordinary shape for any field with more than one
    widget. Three of four variants of the same genuine failure are missed.

So 2.5.3's real scope is narrower than "push buttons": push buttons whose field and widget are
one dictionary. The cell stays uninvoked and unproven.
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

from formats.pdf.detectors.label_in_name import _accessible_name, _is_pushbutton  # noqa: E402

NBSP, ZWSP, SHY = " ", "​", "­"


def _predicate(caption: str, name: str) -> bool:
    """Exactly the comparison `label_in_name.detect` makes. Kept as a local mirror because the
    module inlines it; if it is ever extracted, import it instead and delete this."""
    return caption.lower() in name.lower()


# (caption, accessible name, 2.5.3 is actually satisfied, why it is a hazard)
CASES = [
    ("Submit", "Submit the application form", True, "plain containment"),
    ("Go", "btn_primary_47", False, "genuine failure: machine identifier"),
    ("Save", "save", True, "case difference only"),
    ("Don’t Save", "Don't Save changes", True, "curly vs straight apostrophe"),
    (f"Save{NBSP}File", "Save File now", True, "non-breaking space"),
    ("Next  Step", "Next Step of 3", True, "doubled space"),
    (f"Search{ZWSP}", "Search the catalogue", True, "zero-width space"),
    (unicodedata.normalize("NFD", "Résumé"),
     unicodedata.normalize("NFC", "Résumé") + " upload", True, "NFD vs NFC accents"),
    (f"Print{SHY} Preview", "Print Preview", True, "soft hyphen"),
]


def _score():
    fp = [w for cap, name, ok, w in CASES if ok and not _predicate(cap, name)]
    fn = [w for cap, name, ok, w in CASES if not ok and _predicate(cap, name)]
    return fp, fn


def test_the_predicate_is_deterministic_which_is_not_the_same_as_correct():
    """The premise, pinned first: the comparison really is exact and repeatable. This is what
    the registration's HIGH confidence describes, and it is true."""
    for cap, name, _ok, _why in CASES:
        assert _predicate(cap, name) == _predicate(cap, name)
    assert _predicate("Submit", "Submit the form")
    assert not _predicate("Go", "btn_primary_47")


def test_THE_CORRECTION_it_false_positives_on_ordinary_text_normalization():
    """The claim being corrected. Six of nine realistic pairs are reported as 2.5.3 failures
    while the accessible name contains the visible label as any reader would see it."""
    fp, _fn = _score()
    assert len(fp) >= 6, (
        f"only {len(fp)} normalization false positives now ({fp}) — if the comparison learned to "
        f"normalize, update this file's docstring and the note in "
        f"tests/test_input_purpose_precision.py, which cites this measurement")
    for hazard in ("curly vs straight apostrophe", "non-breaking space", "soft hyphen"):
        assert hazard in fp, f"expected {hazard!r} to still false-positive"


def test_it_still_catches_the_failure_it_is_for():
    """The control. A detector that flagged everything would also score six false positives, and
    would be a different (easier) problem. The genuine failure is still detected and the two
    clean cases are still clean."""
    _fp, fn = _score()
    assert fn == [], f"the predicate started passing genuine failures: {fn}"
    assert not _predicate("Go", "btn_primary_47"), "the real 2.5.3 failure must still be caught"


def test_case_folding_is_the_only_normalization_applied():
    """Names the shape of the defect precisely, so a fix is aimed rather than guessed. Case is
    handled; nothing else is. A fix would fold whitespace, strip default-ignorable characters
    (ZWSP, SHY), normalize to NFC, and map typographic punctuation to ASCII."""
    assert _predicate("SAVE", "save the file"), "case folding works"
    assert not _predicate("save  file", "save file"), "whitespace is not folded"
    assert not _predicate(f"save{ZWSP}", "save"), "default-ignorables are not stripped"
    assert not _predicate(unicodedata.normalize("NFD", "é"),
                          unicodedata.normalize("NFC", "é")), "unicode form is not normalized"


def test_two_applicability_risks_found_by_reading_are_NOT_measured_here():
    """Recorded as an explicit gap rather than left implied, because an unmeasured risk that
    nobody wrote down is indistinguishable from one that was ruled out.

    Both were found by reading `label_in_name.detect`, and both would cause MISSED detections
    (false negatives), not false positives, so they do not affect the numbers above:

      1. `/Ff` is an INHERITABLE field attribute (ISO 32000 §12.7.3.1), but `_is_pushbutton`
         reads `field.get("/Ff")` on the terminal field only. A push button that inherits its
         flag from a parent field reads as `0` and is skipped.
      2. `/MK` lives on the WIDGET annotation. For a field whose widgets are `/Kids`, the caption
         is on the kid, so `_caption(field)` returns None and the field is skipped.

    Confirming either needs a real PDF built with that structure and a real scan, which is the
    separate piece of work this file's header says is still owed. This test asserts only that
    the source still has the shape described, so the note cannot silently go stale."""
    src = (ROOT / "api" / "formats" / "pdf" / "detectors" / "label_in_name.py").read_text()
    assert 'field.get("/Ff")' in src, (
        "the /Ff read changed — re-check whether inherited pushbutton flags are now handled, "
        "and update this note")
    assert 'mk = field.get("/MK")' in src, (
        "the /MK read changed — re-check whether widget /Kids captions are now found")
    # And the helpers this file's numbers depend on still exist with the same meaning.
    assert callable(_is_pushbutton) and callable(_accessible_name)


# ── real scan dispatch: the same questions, asked of real PDFs ───────────────────
#
# Everything above measures the PREDICATE. This section builds real AcroForm documents with
# pikepdf and calls `label_in_name.detect(path)` — the detector's actual entry point — so what is
# asserted is what a scan would report, not what a helper computes. The header's note that real
# dispatch was "still owed" is discharged here.
FLAG_PUSHBUTTON = 1 << 16


def _form(path, buttons, *, pushbutton=True):
    """A real single-page AcroForm. `buttons` is (caption, accessible name, field name);
    caption None means no /MK at all."""
    import pikepdf
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 200))
    fields, annots = [], []
    for cap, tu, t in buttons:
        d = {"/Type": pikepdf.Name.Annot, "/Subtype": pikepdf.Name.Widget,
             "/FT": pikepdf.Name.Btn, "/Ff": FLAG_PUSHBUTTON if pushbutton else 0,
             "/Rect": pikepdf.Array([10, 10, 100, 40]), "/T": pikepdf.String(t)}
        if cap is not None:
            d["/MK"] = pikepdf.Dictionary(CA=pikepdf.String(cap))
        if tu is not None:
            d["/TU"] = pikepdf.String(tu)
        obj = pdf.make_indirect(pikepdf.Dictionary(d))
        fields.append(obj)
        annots.append(obj)
    pdf.pages[0].Annots = pikepdf.Array(annots)
    pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array(fields), DA=pikepdf.String("/Helv 0 Tf 0 g")))
    pdf.save(str(path))
    return path


def _detect(path):
    from formats.pdf.detectors import label_in_name
    return label_in_name.detect(path)


def test_REAL_DISPATCH_positive_control(tmp_path):
    """A genuine 2.5.3 failure through the real detector: the visible caption is "Go" and the
    accessible name is a developer identifier, so a speech-input user saying "Go" cannot
    activate it."""
    pdf = _form(tmp_path / "fail.pdf", [("Go", "btn_primary_47", "f1")])
    found = _detect(pdf)
    assert len(found) == 1, f"the positive control was not reported: {found}"
    assert found[0]["ruleId"] == "PDF_LABEL_NOT_IN_NAME"
    assert found[0]["wcag"].startswith("2.5.3")


@pytest.mark.parametrize("caption,name,why", [
    ("Submit", "Submit the application form", "name contains the label"),
    ("Save", "save the document", "case difference only"),
])
def test_REAL_DISPATCH_negative_controls(tmp_path, caption, name, why):
    """Compliant buttons through the real detector. Without these, "it reported the failure"
    would be consistent with "it reports everything"."""
    pdf = _form(tmp_path / "ok.pdf", [(caption, name, "f1")])
    assert _detect(pdf) == [], f"a compliant button was reported ({why})"


@pytest.mark.parametrize("caption,name,hazard", [
    ("Don\u2019t Save", "Don't Save changes", "curly vs straight apostrophe"),
    ("Save" + NBSP + "File", "Save File now", "non-breaking space"),
])
def test_REAL_DISPATCH_the_normalization_false_positives_reproduce(tmp_path, caption, name, hazard):
    """The correction this file exists for, confirmed end to end rather than in the predicate
    alone: these buttons work fine for a speech-input user, and a real scan reports them
    SERIOUS."""
    pdf = _form(tmp_path / "fp.pdf", [(caption, name, "f1")])
    assert len(_detect(pdf)) == 1, (
        f"{hazard} no longer false-positives through real dispatch — if the comparison learned "
        f"to normalize, update this file's numbers and its header")


def test_REAL_DISPATCH_out_of_scope_controls(tmp_path):
    """Two things the detector correctly declines to judge: a button with no visible caption
    (nothing to compare against) and a checkbox — not a push button, and /MK /CA on one holds the
    check STYLE character rather than a label, so comparing it would be nonsense."""
    no_caption = _form(tmp_path / "nocap.pdf", [(None, "anything", "f1")])
    assert _detect(no_caption) == []
    checkbox = _form(tmp_path / "cb.pdf", [("4", "Agree to terms", "f1")], pushbutton=False)
    assert _detect(checkbox) == []


def _kids_form(path, *, ff_on_parent: bool, mk_on_parent: bool):
    """A field whose widget is a separate /Kids entry — the ordinary shape for any field with
    more than one widget, and what many form designers emit even for one. The button is the same
    genuine 2.5.3 failure in every variant: caption "Go", accessible name "btn_primary_47"."""
    import pikepdf
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 200))
    widget = {"/Type": pikepdf.Name.Annot, "/Subtype": pikepdf.Name.Widget,
              "/Rect": pikepdf.Array([10, 10, 100, 40])}
    parent = {"/FT": pikepdf.Name.Btn, "/T": pikepdf.String("f1"),
              "/TU": pikepdf.String("btn_primary_47")}
    (parent if ff_on_parent else widget)["/Ff"] = FLAG_PUSHBUTTON
    (parent if mk_on_parent else widget)["/MK"] = pikepdf.Dictionary(CA=pikepdf.String("Go"))
    w = pdf.make_indirect(pikepdf.Dictionary(widget))
    p = pdf.make_indirect(pikepdf.Dictionary(parent))
    p.Kids = pikepdf.Array([w])
    w.Parent = p
    pdf.pages[0].Annots = pikepdf.Array([w])
    pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([p]), DA=pikepdf.String("/Helv 0 Tf 0 g")))
    pdf.save(str(path))
    return path


@pytest.mark.parametrize("ff_parent,mk_parent,detected", [
    (True, True, True),      # field and widget merged into one dictionary
    (True, False, False),    # /MK on the widget
    (False, True, False),    # /Ff on the widget
    (False, False, False),   # both on the widget — the commonest real shape
])
def test_REAL_DISPATCH_the_two_applicability_risks_are_REAL_false_negatives(
        tmp_path, ff_parent, mk_parent, detected):
    """THE GAP, measured instead of merely recorded.

    An earlier version of this file listed two risks found by READING — /Ff is an inheritable
    attribute but is read only off the terminal field, and /MK lives on the widget annotation —
    and said confirming either needed a real PDF and a real scan. Built and run:

        /Ff on parent, /MK on parent  -> detected
        /Ff on parent, /MK on widget  -> MISSED
        /Ff on widget, /MK on parent  -> MISSED
        /Ff on widget, /MK on widget  -> MISSED

    Both are real, and only the fully-merged shape is seen. So 2.5.3's actual scope is narrower
    than its registration's "push buttons": it is push buttons whose FIELD AND WIDGET ARE ONE
    DICTIONARY. Every variant here is the same genuine failure; three of four are invisible.

    This is a COVERAGE gap, not a precision one — it causes missed detections, never false
    reports — so it does not move the numbers at the top of this file. It does mean the
    registration's PARTIAL coverage is optimistic about which fields it can see."""
    pdf = _kids_form(tmp_path / f"kids-{ff_parent}-{mk_parent}.pdf",
                     ff_on_parent=ff_parent, mk_on_parent=mk_parent)
    found = _detect(pdf)
    if detected:
        assert len(found) == 1, "the merged field/widget shape must still be detected"
    else:
        assert found == [], (
            "a /Kids shape is now detected — good, but this file's scope claim and the "
            "registration's coverage both need restating")


def test_the_cell_is_still_uninvoked_by_any_scan():
    """Everything above calls `detect` directly, which is what "real scan dispatch" can mean for
    this detector: `office_structure.checks_for` — what an actual scan calls — never invokes it.
    Measuring it does not enable it, and it stays disabled pending its own decision."""
    import office_structure
    src = Path(office_structure.__file__).read_text()
    body = src[src.index("def checks_for"):][:8000]
    assert "label_in_name" not in body, (
        "label_in_name is now reachable from checks_for. That is a product decision — record it "
        "in tests/test_orphaned_detectors.py and delete this assertion")
