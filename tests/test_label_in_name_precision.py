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

WHAT IS STILL OWED. This measures the PREDICATE in isolation. It does not exercise real scan
dispatch, and it does not test the two applicability risks found by reading the source rather
than running it, which are recorded in the last test below as an explicit gap. Evaluating 2.5.3
through a real scan with positive and negative controls is separate work, and until it is done
the cell stays uninvoked and unproven.
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

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
