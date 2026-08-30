"""1.3.3 Sensory Characteristics across xlsx, pptx and pdf — one criterion, one mechanism.

WHY THIS FILE EXISTS RATHER THAN THREE ADDITIONS. Every other pair in the corpora is decided by
reading a file's STRUCTURE, so its fixture and its assertions belong with its format. 1.3.3 is
decided by reading the document's PROSE: `textchecks.detect_sensory` looks for an instruction that
identifies a control only by shape, colour or position ("the round green button on the right").
The words are the fixture; the container is incidental.

That makes the cross-format sameness the property actually worth protecting, and it is not
visible from inside any one format's test file. All three corpora seed the IDENTICAL sentence, so
a change in detector behaviour shows up as one result in three places rather than three arguments
about three different sentences.

WHY 1.3.3 WAS REACHABLE WHEN ITS NEIGHBOURS WERE NOT. 1.3.1, 1.3.2 (on Office), 2.4.2 and 3.1.1
(on pptx) need the .NET analyser; 1.4.5 needs tesseract; 3.1.2 needs langdetect. 1.3.3 needs none
of them — it is a text predicate over extracted text, so it runs wherever the suite runs. That is
why it is in each corpus's DECLARED and not its DECLARED_ENGINE.

THE DETECTOR IS DRIVEN THROUGH `content_findings`, not `detect_sensory` directly. That is the
function the scan path calls, and it guards each sub-check separately — which is the reason 1.3.3
still works on a box with no langdetect, where 3.1.2 inside the same call quietly returns nothing.
Calling the inner predicate would test a function; calling this tests the lane.
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
import pii as _pii  # noqa: E402
import textchecks as _tc  # noqa: E402

CORPORA = [("xlsx", "gen_xlsx_corpus"), ("pptx", "gen_pptx_corpus"), ("pdf", "gen_pdf_corpus")]
VIOLATION = "sensory-instruction"
CONTROL = "sensory-instruction-ok"


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
        d = Path(tempfile.mkdtemp(prefix=f"acp-sensory-{fmt}-")) / "docs"
        manifest, problems = gen.build_all(d)
        assert not problems, f"{fmt}: {problems}"
        out[fmt] = (gen, d.parent, {r["name"]: r for r in manifest})
    return out


def _text_wcags(path: Path) -> set[str]:
    """The criteria a real scan's TEXT lane reports for this file — the same two calls
    handlers._propose_text_findings makes: extract, then content_findings."""
    text = _pii.extract_text(path) or ""
    return {(f.get("wcag") or "").split()[0] for f in _tc.content_findings(text) if f.get("wcag")}


# ── the label is earned, on every format ─────────────────────────────────────────

@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_sensory_violation_is_actually_detected(built, fmt):
    _gen, out, rows = built[fmt]
    fired = _text_wcags(out / rows[VIOLATION]["file"])
    assert "1.3.3" in fired, (
        f"{fmt}: the sensory fixture declares 1.3.3 but the text lane reported "
        f"{sorted(fired) or 'nothing'} — the instruction is not being read as sensory-only")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_rewritten_instruction_is_not_flagged(built, fmt):
    """The control carries the SAME instruction with the control named and the section named. If
    this fired, the detector would be keying on something other than the sensory reference — and
    the violation fixture above would prove nothing."""
    _gen, out, rows = built[fmt]
    fired = _text_wcags(out / rows[CONTROL]["file"])
    assert "1.3.3" not in fired, (
        f"{fmt}: the rewritten instruction was flagged — a false positive")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_text_actually_survives_extraction(built, fmt):
    """The failure this catches is a fixture that passes for the wrong reason. If extraction
    returned nothing, the control would look clean and the violation would look like a detector
    bug — so assert the words are really in the extracted text before believing either verdict."""
    _gen, out, rows = built[fmt]
    for name in (VIOLATION, CONTROL):
        text = (_pii.extract_text(out / rows[name]["file"]) or "").lower()
        assert "payment" in text, (
            f"{fmt}/{name}: extraction produced no usable text, so neither verdict means anything")


# ── the three corpora agree about what the fixture says ──────────────────────────

def test_all_three_corpora_seed_the_identical_sentence(built):
    """The point of the shared file. Three near-identical sentences would let a detector change
    pass on two formats and fail on the third for a reason nobody could see — and the natural
    reaction would be to edit the odd sentence until it matched, which hides the finding."""
    bad = {fmt: gen.SENSORY_BAD for fmt, (gen, _o, _r) in built.items()}
    ok = {fmt: gen.SENSORY_OK for fmt, (gen, _o, _r) in built.items()}
    assert len(set(bad.values())) == 1, f"the violation wording has diverged: {bad}"
    assert len(set(ok.values())) == 1, f"the control wording has diverged: {ok}"


def test_the_control_differs_only_by_removing_the_sensory_reference(built):
    """Both sentences give the same instruction about the same thing. What changes is HOW the
    control is identified — by name and section rather than by shape, colour and position."""
    gen = built["pdf"][0]
    for word in ("round", "green", "right", "below"):
        assert word in gen.SENSORY_BAD.lower(), f"the violation lost its {word!r} reference"
        assert word not in gen.SENSORY_OK.lower(), (
            f"the control still says {word!r} — it is not a clean counterpart")
    for word in ("submit", "payment"):
        assert word in gen.SENSORY_OK.lower()


# ── it is declared everywhere, and declared as reachable ─────────────────────────

@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_133_is_declared_and_not_engine_gated(built, fmt):
    """1.3.3 belongs in DECLARED, not DECLARED_ENGINE: unlike xlsx 2.4.2/3.1.1 it needs no
    analyser, so its label holds on a bare checkout as well as in CI. Putting it in the
    engine-only set would understate the guarantee — the mirror image of the over-claim that set
    exists to prevent."""
    gen, _out, _rows = built[fmt]
    assert "1.3.3" in gen.DECLARED, f"{fmt} no longer declares 1.3.3"
    assert "1.3.3" not in set(getattr(gen, "DECLARED_ENGINE", ())), (
        f"{fmt} declares 1.3.3 as engine-only, but it is a text predicate with no engine")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_133_is_review_lane_so_neither_fixture_may_claim_pass(built, fmt):
    """A clean sensory result means "no sensory-only instruction was matched", not "this document
    is understandable without sensory cues" — which is a judgement. So 1.3.3 cannot certify on any
    of these formats, and the control expects REVIEW."""
    _gen, _out, rows = built[fmt]
    assert not ce.can_ever_pass("1.3.3", fmt), (
        f"1.3.3 became certifiable on {fmt} — revisit the control's expected verdict")
    assert rows[CONTROL]["expect"]["1.3.3"] == "REVIEW"
    assert rows[VIOLATION]["expect"]["1.3.3"] == "FAIL"
