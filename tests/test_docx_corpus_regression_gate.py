"""The labelled .docx corpus, as a CI gate rather than a script somebody remembers to run.

WHY THIS EXISTS. Every gap found on 2026-08-09 — the decorative predicate disagreeing with
itself at three sites, an empty heading matching no check at all, the OCR cap truncating in
silence — was invisible because nothing asserted the whole surface at once. Each individual
detector had tests and each passed. What was missing was one thing that says: given 32 documents
whose correct answer is known, does the engine still get all of them right?

That question has a shelf life of exactly one commit unless CI asks it.

WHAT IT ASSERTS, AND WHY NOT MORE. Zero false passes and zero false positives are absolute — a
false pass is a conformance claim on an inaccessible document, which is the outcome ADR 0016
exists to prevent, and a false positive is what erodes a reviewer's trust in the tool. Recall is
asserted per criterion rather than in aggregate, so a regression on one SC cannot be averaged
away by fifteen others.

Notably NOT asserted: the exact finding COUNT per rule. Detectors legitimately gain and merge
findings (a heading skip reports under both 1.3.1 and 2.4.6, and that is correct), so pinning
counts would make every honest improvement look like a regression and the gate would be relaxed
until it meant nothing.

THE SKIP IS THE DANGEROUS PART, and it is why `test_the_gate_actually_ran` exists. A gate that
self-skips in a stripped environment is a check that cannot fail, and this repo has already been
bitten by exactly that shape twice — a pipeline whose exit status came from `tail`, and a
`grep ... || echo clean` that printed "clean" because nothing ran. So: the Office engine's
absence skips honestly (it is a build step, not a code fact), but if it IS present the gate
asserts a FLOOR on how many criteria were exercised. A run that quietly measures two SCs and
passes is the failure this file is most likely to suffer, so it is the one made impossible.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

from engines import OFFICE_OK  # noqa: E402

pytestmark = pytest.mark.skipif(
    not OFFICE_OK,
    reason="Office .NET CLI not built — the corpus measures the engine, so scoring it without "
           "one would assert that a silent engine is correct")


def _ocr_ok() -> bool:
    import ocr
    return ocr.is_available()


# Criteria that CANNOT be detected without tesseract, so a run without it must not score them as
# missed. 1.4.5 (images of text) is OCR by definition — the detector reads text out of the image.
#
# This is not a hypothetical accommodation. The gate shipped assuming tesseract, because the
# machine it was written on had it; the repo's OTHER pipeline (azure-pipelines.yml) ran the same
# suite without it and reported "1.4.5: found 0 of 1" — a red build describing an environment gap
# as a product regression. Both pipelines now install it, and this is the belt to that braces: a
# fresh clone, a dev box, or a third pipeline should get an honest partial answer rather than a
# false accusation.
#
# Narrowing coverage silently would be the worse failure, so `test_ocr_criteria_are_covered_in_ci`
# fails when the exclusion is in force somewhere it should not be.
_NEEDS_OCR = frozenset({"1.4.5"})


@pytest.fixture(scope="module")
def scored(tmp_path_factory):
    """Build the corpus into a temp directory and score it, once for the whole module.

    Generated here rather than committed: the fixtures are ~30 small .docx files that
    `gen_sc_corpus.py` writes deterministically, and a generated corpus cannot drift from the
    generator that documents what each fixture is FOR. It also keeps the repo free of binaries
    whose provenance a reviewer would have to take on trust.
    """
    import gen_sc_corpus
    import score_assessment

    out = tmp_path_factory.mktemp("sc-corpus")
    docs = out / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    manifest, problems = [], []
    for name, build, post, kind in gen_sc_corpus.FIXTURES:
        d = gen_sc_corpus._doc()
        expectations, note = build(d)
        path = docs / f"{name}.docx"
        d.save(path)
        if post:
            post(path)
        problems += gen_sc_corpus._validate(name, expectations)
        manifest.append({"file": f"docs/{name}.docx", "name": name, "kind": kind,
                         "format": gen_sc_corpus.FMT, "expect": expectations, "note": note})
    assert not problems, f"fixtures declare verdicts the engine cannot emit: {problems}"

    ce = gen_sc_corpus.ce
    scs = sorted(sc for sc, f in ce.pol.SCOPE_PRESETS["acp-core-17"].items()
                 if gen_sc_corpus.FMT in f)
    (out / "manifest.json").write_text(json.dumps({
        "format": gen_sc_corpus.FMT, "fixtures": manifest,
        "lanes": {sc: {"clean_verdict": ce.clean_verdict(sc, gen_sc_corpus.FMT),
                       "possible": sorted(ce.possible_verdicts(sc, gen_sc_corpus.FMT)),
                       "can_pass": ce.can_ever_pass(sc, gen_sc_corpus.FMT)} for sc in scs},
    }) + "\n")

    return score_assessment.score_corpus(out, verbose=False)


# ── the gate cannot pass vacuously ────────────────────────────────────────────

def test_the_gate_actually_ran(scored):
    """A floor on coverage, so a stripped environment fails instead of passing quietly.

    This is the assertion that makes the rest of the file worth having. Without it, anything
    that stopped the engine producing findings — a missing dependency, a changed entry point, a
    swallowed exception — would show up as zero violations found, zero false positives, and a
    green gate.
    """
    seeded = scored["seeded"]
    assert seeded >= 15, (
        f"only {seeded} seeded violations were scored — the corpus should present ~21. "
        "Something stopped the engine seeing them, and a gate that measures nothing passes.")

    # DETECTIONS, not tallies — and this distinction was found by testing the test. The first
    # version counted criteria with any tally entry, including `tn`, so a completely silent
    # engine still "exercised" a dozen criteria: with no findings at all, every PASS-capable
    # pair certifies clean and lands in `tn`. Simulating a silent engine failed four other
    # assertions and left THIS one green — the guard against vacuous passes was itself vacuous.
    detected = [sc for sc, t in scored["per_sc"].items() if t["tp"]]
    assert len(detected) >= 8, (
        f"only {len(detected)} criteria actually detected anything: {detected}. "
        "The engine is not producing findings, so nothing below is a measurement of it.")


# ── the two absolutes ─────────────────────────────────────────────────────────

def test_no_false_pass(scored):
    """A real violation CERTIFIED as conformant. This feeds a VPAT; it is the one outcome that
    reaches a customer as a written claim, and the one ADR 0016 exists to prevent."""
    assert scored["false_pass"] == 0, (
        f"{scored['false_pass']} seeded violation(s) were certified as passing")


def test_no_false_positives(scored):
    """Flagged something compliant. Cheap per instance and expensive in aggregate — a reviewer
    who dismisses ten spurious findings stops reading the eleventh."""
    assert scored["false_positive"] == 0, (
        f"{scored['false_positive']} compliant thing(s) were flagged as failing")


# ── per criterion, so one regression cannot be averaged away ──────────────────

def test_every_seeded_violation_is_detected(scored):
    """Recall per SC, not in aggregate.

    An aggregate recall of 0.95 hides one criterion at zero, and "which criterion" is exactly
    what a customer asks. Reported as a list so a failure names every affected SC at once rather
    than one per re-run.
    """
    skip = set() if _ocr_ok() else _NEEDS_OCR
    missed = []
    for sc, t in scored["per_sc"].items():
        if sc in skip:
            continue
        positives = t["tp"] + t["fn_pass"] + t["abstain_on_fail"]
        if positives and t["tp"] < positives:
            missed.append(f"{sc}: found {t['tp']} of {positives}")
    assert not missed, "criteria that missed a seeded violation — " + "; ".join(missed)


def test_ocr_criteria_are_covered_in_ci():
    """The exclusion above must be a fallback, never the normal state.

    An environment-conditional skip is one edit away from being how a criterion stops being
    tested at all: it goes quiet, nothing fails, and the coverage loss is visible only to
    somebody reading the skip logic. So on CI — where both pipelines now install tesseract —
    the absence of OCR is itself the failure, and the message says which pipeline to fix.

    Off CI this passes regardless: a dev box without tesseract should get an honest partial
    answer, not a red suite about a dependency it never agreed to install.
    """
    import os
    on_ci = os.environ.get("CI") or os.environ.get("TF_BUILD")     # GitHub Actions | Azure
    if not on_ci:
        pytest.skip("not CI — a local run may legitimately lack tesseract")
    assert _ocr_ok(), (
        "tesseract is missing on CI, so " + ", ".join(sorted(_NEEDS_OCR)) + " went unexercised. "
        "Both .github/workflows/ci.yml and azure-pipelines.yml install it; whichever runner "
        "this is, its install step is missing or failed.")


def test_the_deterministic_lane_still_certifies(scored):
    """The four PASS-capable pairs (1.3.1, 1.4.3, 2.4.2, 3.1.1) are the only ones that can
    certify at all. If one stops, ACP quietly loses the ability to say a document conforms —
    which shows up as caution, not as an error, and so is easy to miss."""
    assert scored["macro_f1_deterministic"] == pytest.approx(1.0), (
        f"deterministic-lane macro-F1 fell to {scored['macro_f1_deterministic']:.2f}")
    assert scored["certified_clean"] > 0, "nothing certified clean — the PASS lane went silent"


def test_the_review_lane_holds(scored):
    assert scored["macro_f1_review"] == pytest.approx(1.0), (
        f"review-lane macro-F1 fell to {scored['macro_f1_review']:.2f}")


def test_attribution_is_clean(scored):
    """Detected-but-mislabelled is a different defect from not-noticing, with a different fix,
    and it is invisible in recall — the finding is there, under the wrong criterion."""
    assert not scored["attribution"], (
        "criteria blamed for the wrong defect: "
        + "; ".join(f"{n} seeded {s} -> {b}" for n, s, b in scored["attribution"]))
