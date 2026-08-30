"""3.1.2 Language of Parts across xlsx, pptx and pdf — one criterion, three different ceilings.

WHY A SHARED FILE, like 1.3.3's. 3.1.2 is decided by the document's PROSE: `detect_language_parts`
needs two or more segments of at least twelve real words in two or more confidently-detected
languages, and reports the passages whose language the document never identifies. The words are
the fixture; the container is incidental. All three corpora seed the IDENTICAL English body and
the IDENTICAL French passage, so a detector change shows up as one result in three places rather
than three arguments about three different paragraphs.

WHAT IS NOT SHARED, AND IS THE REASON THIS FILE EARNS ITS KEEP. The three formats do not have the
same ceiling, and the difference is not a coverage gap somebody can close with another fixture:

  * .pptx CAN record the mark. `a:rPr lang="fr-FR"` on the run, read back by
    office_structure.language_marked_spans, and the finding clears. So .pptx gets a THIRD fixture
    — the same mixed-language deck with the French marked — which proves the criterion is
    remediable there rather than merely detectable.
  * .xlsx CANNOT. SpreadsheetML's rich-text run properties (CT_RPrElt) have no language element
    at all, so there is nowhere in the format to record the answer and no write can ever clear
    3.1.2 on a spreadsheet.
  * .pdf CANNOT either, for a different reason: it would need a /Lang walk of the structure tree,
    and that is not built.

Both of those were claims in `language_marked_spans`' docstring — "verified against the schema",
"not built". They are now verified by RUNNING: `test_marking_the_passage_clears_it_only_on_pptx`
applies the same marking intent to all three formats and asserts it clears exactly one. That
matters because the natural reaction to a monolingual control is to "improve" it into a marked
one, which on two of these formats would produce a fixture that fails 3.1.2 identically to the
violation and would read as a detector bug.

THE DETECTOR IS DRIVEN THROUGH `content_findings` WITH THE MARKS, which is the pair of calls the
scan path makes (scanner.py:3483). Calling `detect_language_parts` directly would test a function;
this tests the lane — and passing the marks is load-bearing, because without them a correctly
marked document is indistinguishable from an unmarked one.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import corpus_expectations as ce  # noqa: E402
import office_structure as osx  # noqa: E402
import pii as _pii  # noqa: E402
import textchecks as _tc  # noqa: E402

CORPORA = [("xlsx", "gen_xlsx_corpus"), ("pptx", "gen_pptx_corpus"), ("pdf", "gen_pdf_corpus")]
VIOLATION = "language-parts"
CONTROL = "language-parts-ok"
MARKED_CONTROL = "language-parts-marked-ok"        # .pptx only, by format capability

pytestmark = pytest.mark.skipif(
    not _tc._langdetect_available(),
    reason="langdetect is unavailable, so 3.1.2 cannot be exercised here; both CI pipelines "
           "install it from api/requirements.txt")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built():
    """Each corpus built once: {format: (module, out_dir, {name: row})}."""
    out = {}
    for fmt, name in CORPORA:
        gen = _load(name)
        d = Path(tempfile.mkdtemp(prefix=f"acp-lang-{fmt}-")) / "docs"
        manifest, problems = gen.build_all(d)
        assert not problems, f"{fmt}: {problems}"
        out[fmt] = (gen, d.parent, {r["name"]: r for r in manifest})
    return out


def _text_wcags(path: Path, ext: str) -> set[str]:
    """The criteria a real scan's TEXT lane reports — extract, read the document's own language
    marks, judge. The two calls scanner.py makes."""
    text = _pii.extract_text(path) or ""
    return {(f.get("wcag") or "").split()[0]
            for f in _tc.content_findings(text, osx.language_marked_spans(path, ext))
            if f.get("wcag")}


# ── the label is earned, on every format ─────────────────────────────────────────

@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_unmarked_foreign_passage_is_detected(built, fmt):
    _gen, out, rows = built[fmt]
    fired = _text_wcags(out / rows[VIOLATION]["file"], f".{fmt}")
    assert "3.1.2" in fired, (
        f"{fmt}: the fixture declares 3.1.2 but the text lane reported "
        f"{sorted(fired) or 'nothing'} — the French passage is not being read as a foreign part")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_monolingual_control_is_not_flagged(built, fmt):
    """The control carries the same body with the French paragraph replaced by an English one of
    the same length. If this fired, the detector would be keying on something other than the
    language mix and the violation above would prove nothing."""
    _gen, out, rows = built[fmt]
    fired = _text_wcags(out / rows[CONTROL]["file"], f".{fmt}")
    assert "3.1.2" not in fired, f"{fmt}: a single-language document was flagged — a false positive"


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_text_actually_survives_extraction(built, fmt):
    """The failure this catches is a fixture that passes for the wrong reason. If extraction
    returned nothing, the control would look clean and the violation would look like a detector
    bug — so assert the words really are in the extracted text before believing either verdict.

    The French is checked by a word that survives the accent-stripping the fixtures use, because
    an extractor that dropped it would otherwise leave a green test and a dead fixture."""
    _gen, out, rows = built[fmt]
    for name in (VIOLATION, CONTROL):
        text = (_pii.extract_text(out / rows[name]["file"]) or "").lower()
        assert "benefits office" in text, (
            f"{fmt}/{name}: extraction produced no usable text, so neither verdict means anything")
    bad = (_pii.extract_text(out / rows[VIOLATION]["file"]) or "").lower()
    assert "avantages sociaux" in bad, (
        f"{fmt}: the French passage did not survive extraction, so 3.1.2 fired on something else")


# ── the three corpora agree about what the fixture says ──────────────────────────

def test_all_three_corpora_seed_the_identical_prose(built):
    """The point of the shared file. Three near-identical passages would let a detector change
    pass on two formats and fail on the third for a reason nobody could see — and the natural
    reaction would be to edit the odd one until it matched, which hides the finding."""
    en = {fmt: gen.LANG_EN_BODY for fmt, (gen, _o, _r) in built.items()}
    fr = {fmt: gen.LANG_FR_PASSAGE for fmt, (gen, _o, _r) in built.items()}
    tail = {fmt: gen.LANG_EN_TAIL for fmt, (gen, _o, _r) in built.items()}
    assert len(set(en.values())) == 1, f"the English body has diverged: {en}"
    assert len(set(fr.values())) == 1, f"the French passage has diverged: {fr}"
    assert len(set(tail.values())) == 1, f"the control's replacement has diverged: {tail}"


def test_every_segment_clears_the_detectors_word_floor(built):
    """`_MIN_SEG_WORDS` is 12 and it is counted on the SEGMENT, so a passage under it is skipped
    rather than judged — a fixture that fell under the floor would go quiet for a reason that has
    nothing to do with language. Asserted against the constant rather than a number typed here, so
    raising the floor fails this instead of silently retiring the corpus."""
    gen = built["pdf"][0]
    for seg in list(gen.LANG_EN_BODY) + [gen.LANG_FR_PASSAGE, gen.LANG_EN_TAIL]:
        assert len(seg.split()) >= _tc._MIN_SEG_WORDS, (
            f"{seg[:40]!r} has {len(seg.split())} words, under the detector's floor of "
            f"{_tc._MIN_SEG_WORDS} — it would be skipped, not judged")


# ── the format ceilings differ, and that is measured rather than described ───────

def test_marking_the_passage_clears_it_only_on_pptx(built):
    """The asymmetry, run rather than read.

    `language_marked_spans` documents that .xlsx has no per-run language element ("verified
    against the schema") and that .pdf's /Lang walk "is not built". Both are claims about what a
    write could ever achieve, and both are load-bearing: they are why the .xlsx and .pdf controls
    are MONOLINGUAL rather than marked. If either were wrong, those controls would be understating
    what the format can do, and the honest fixture would be a marked one.

    So this applies the marking intent to all three and asserts exactly one clears. It is also the
    guard against the obvious "improvement": someone reading the monolingual controls as lazy and
    replacing them with marked ones would, on two of three formats, produce a fixture that fails
    3.1.2 identically to the violation and reads as an engine bug."""
    _gen, out, rows = built["pptx"]
    marked = out / rows[MARKED_CONTROL]["file"]
    assert "fr" in osx.language_marked_spans(marked, ".pptx"), (
        "the .pptx marked fixture carries no fr mark — the fixture, not the format, is broken")
    assert "3.1.2" not in _text_wcags(marked, ".pptx"), (
        "marking the French run lang=\"fr-FR\" no longer clears 3.1.2 on .pptx — the one format "
        "where this criterion is remediable has stopped being so")

    for fmt in ("xlsx", "pdf"):
        _g, o, r = built[fmt]
        assert osx.language_marked_spans(o / r[VIOLATION]["file"], f".{fmt}") == {}, (
            f"language_marked_spans now returns marks for .{fmt}. If that format grew a way to "
            f"record a passage's language, its control should become a MARKED one like .pptx's "
            f"and this assertion should be deleted — but check the schema first")


def test_the_marked_deck_differs_from_the_violation_only_by_the_mark(built):
    """Same prose, same order, same everything a reader sees. If the marked fixture had different
    words in it, its silence would not be attributable to the mark."""
    _gen, out, rows = built["pptx"]
    bad = " ".join((_pii.extract_text(out / rows[VIOLATION]["file"]) or "").split())
    marked = " ".join((_pii.extract_text(out / rows[MARKED_CONTROL]["file"]) or "").split())
    assert bad == marked, (
        "the .pptx violation and its marked counterpart no longer carry identical text — the pair "
        "no longer isolates the language mark")


# ── it is declared everywhere, and declared as reachable ─────────────────────────

@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_312_is_declared_and_not_engine_gated(built, fmt):
    """3.1.2 belongs in DECLARED, not DECLARED_ENGINE: it needs langdetect, which
    api/requirements.txt pins and both CI pipelines install, rather than the .NET analyser that
    only CI builds. Putting it in the engine-only set would understate the guarantee."""
    gen, _out, _rows = built[fmt]
    assert "3.1.2" in gen.DECLARED, f"{fmt} no longer declares 3.1.2"
    assert "3.1.2" not in set(getattr(gen, "DECLARED_ENGINE", ())), (
        f"{fmt} declares 3.1.2 as engine-only, but its dependency is langdetect, not an analyser")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_312_is_review_lane_so_neither_fixture_may_claim_pass(built, fmt):
    """A clean 3.1.2 result means "no unmarked foreign passage was matched above the confidence
    floor", not "every passage's language is correctly identified" — which is a judgement. So
    3.1.2 cannot certify on any of these formats and the controls expect REVIEW (ADR 0016)."""
    _gen, _out, rows = built[fmt]
    assert not ce.can_ever_pass("3.1.2", fmt), (
        f"3.1.2 became certifiable on {fmt} — revisit the controls' expected verdict")
    assert rows[VIOLATION]["expect"]["3.1.2"] == "FAIL"
    assert rows[CONTROL]["expect"]["3.1.2"] == "REVIEW"
