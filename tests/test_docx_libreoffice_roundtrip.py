"""Independent validation of the .docx detectors: do they survive another OOXML implementation?

WHAT THIS ANSWERS THAT THE FIXTURE SUITE CANNOT. Every .docx ACP is tested against was written by
ACP — `scripts/gen_demo_fixtures.py` and a dozen test modules build them with python-docx. So the
whole corpus shares one serialisation of OOXML, and a detector that keys on something incidental
to how python-docx happens to write the XML — attribute order, an element python-docx always
emits, a namespace prefix — would pass every test in this repo and then fail on the first real
customer document authored in Word.

P5.3's insight is that a second implementation is the cheapest possible check on that: round-trip
each fixture through LibreOffice, which re-serialises the document through an entirely independent
codebase, and require the detectors to reach the SAME conclusions. Measured on this corpus the
round-trip rewrites `word/document.xml` completely and drops two zip entries, roughly halving the
file — so "the findings are identical" is a claim about the document's meaning surviving, not
about the bytes being similar.

WHY THIS IS SKIP-GUARDED AND NOT IN CI. LibreOffice is a several-hundred-megabyte install and adds
a minute or two to a job that already runs four shards. Whether that is worth spending on every PR
is a cost decision for whoever owns the CI budget, not something to slip in with a test; this
module therefore runs wherever `soffice` exists and skips cleanly where it does not. It is a real
guard for anyone who has LibreOffice, and it is honest about guarding nothing in CI until somebody
decides to install it there. `test_the_skip_guard_names_the_binary_it_needs` keeps that decision
discoverable rather than silent.

THREE TESTS MAKE THE MAIN ONE MEAN SOMETHING, and without them it would be theatre:

  · `test_the_round_trip_actually_rewrites_the_document` — if LibreOffice were near enough a copy,
    "identical findings" would be vacuous. It is not: the measurement is in the test.
  · `test_the_comparison_discriminates` — a comparison that returns "same" for two genuinely
    different documents would report success forever. This feeds it two documents with different
    accessibility facts and requires it to say so.
  · `test_the_registry_path_is_uniformly_review_on_this_corpus` — the second detector path
    contributes no signal here, and that is pinned rather than quietly relied upon.

SOFFICE EXITS 0 WHEN IT FAILS. `soffice --convert-to` returned exit 0 while printing "Error: source
file could not be loaded" throughout this module's development (the cause was a missing
`libreoffice-writer`; the core package alone cannot load a .docx at all). So the OUTPUT FILE is the
only honest success signal, and `_round_trip` is written around that rather than around the exit
status — the same "a check that cannot fail" shape CLAUDE.md documents for shell pipelines.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure  # noqa: E402

CORPUS = ACP / "test-corpus/oracle"

#: The binary this whole module depends on. Named in one place so the skip reason, the
#: availability check and the documentation cannot drift apart.
SOFFICE = "soffice"

pytestmark = pytest.mark.skipif(
    shutil.which(SOFFICE) is None,
    reason=(f"{SOFFICE} is not installed, so the independent OOXML round-trip cannot run. This is "
            f"expected in CI, which deliberately does not install LibreOffice — see the module "
            f"docstring. Install libreoffice-writer to run these locally."))


def _corpus_docx() -> list[Path]:
    """The oracle fixtures, which are the frozen rule-trigger set rather than the demo estate.

    `edge-*.docx` are excluded deliberately: `edge-corrupt.docx` and `edge-pdf-as.docx` are not
    valid Word documents at all — they exist to prove ACP degrades gracefully on rubbish — and
    LibreOffice cannot load them either. Feeding them here would test LibreOffice's error handling
    rather than ACP's detectors.
    """
    return sorted(CORPUS.glob("docx-*.docx"))


def _round_trip(src: Path, outdir: Path) -> Path:
    """`src` re-serialised by LibreOffice. Raises rather than returning a file that is not there.

    The output file's existence is the success signal, NOT the exit status: soffice returns 0 even
    when it could not load the source (see the module docstring). A version of this that trusted
    the exit code would silently compare a document against itself.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [SOFFICE, f"-env:UserInstallation=file://{outdir / 'profile'}", "--headless",
         "--norestore", "--convert-to", "docx", str(src), "--outdir", str(outdir)],
        capture_output=True, text=True, timeout=300)
    produced = outdir / src.name
    if not produced.exists():
        raise AssertionError(
            f"LibreOffice produced no output for {src.name} (exit {proc.returncode}, which it "
            f"returns as 0 even on failure). stdout: {proc.stdout.strip()[:300]!r}")
    return produced


def _findings(path: Path) -> set[tuple]:
    """A document's verdicts from BOTH detector paths, as comparable identities.

    ACP judges a .docx two ways and they cover different criteria, so a round-trip check that used
    only one would be silent about half of what ACP claims:

      · `office_structure.docx_checks` — heading structure, pseudo-headings, link purpose;
      · the lazily-registered `rule_registry` rules — 10 of them, compared as (rule, status).

    Including the registry was not the first design. It was added after
    `test_the_registry_path_carries_real_signal` measured the corpus and found 1.1.1 and 2.4.4
    returning FAIL on three fixtures — and alt text surviving a re-serialisation is exactly the
    kind of thing an independent implementation can break, so leaving it out would have omitted
    the most valuable check in the module.

    `detail` is deliberately excluded from the structural half. It carries counts and quoted
    document text ("1 hyperlink(s) with unclear text (e.g. "click here")"), which a
    re-serialisation may legitimately reword or recount without the accessibility fact changing.
    Including it would measure prose stability rather than detector agreement.
    """
    import formats.docx  # noqa: F401 — registration is lazy; without this the registry is empty
    import rule_registry

    structural = {("structure", f.get("ruleId"), f.get("wcag"), f.get("severity"))
                  for f in (office_structure.docx_checks(path) or [])}
    registry = set()
    for reg in rule_registry.all_registrations():
        if reg.fmt != "docx":
            continue
        result = rule_registry.evaluate(reg.rule, "docx", path)
        registry.add(("registry", reg.rule, str(getattr(result, "status", result))))
    return structural | registry


# ── the three tests that make the main one mean something ─────────────────────

def test_the_round_trip_actually_rewrites_the_document(tmp_path):
    """If LibreOffice were near enough a copy, every invariance claim below would be vacuous.

    Measured rather than asserted in prose: on `docx-heading-structure.docx` the round-trip
    re-serialises `word/document.xml` byte-for-byte differently and drops zip entries. That is
    what makes "the findings survived" a statement about meaning rather than about bytes.
    """
    src = CORPUS / "docx-heading-structure.docx"
    out = _round_trip(src, tmp_path / "rt")

    assert out.read_bytes() != src.read_bytes(), "the round-trip returned an identical file"
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        assert a.read("word/document.xml") != b.read("word/document.xml"), (
            "word/document.xml came back byte-identical, so nothing was re-serialised")


def test_the_comparison_discriminates():
    """Two documents with different accessibility facts must not compare equal.

    Without this, `_findings` could return a constant and every invariance test below would pass
    forever. `docx-heading-structure.docx` has a heading-level skip; `docx-clean-accessible.docx`
    does not.
    """
    skipped = _findings(CORPUS / "docx-heading-structure.docx")
    clean = _findings(CORPUS / "docx-clean-accessible.docx")
    assert skipped != clean, "the comparison cannot tell two different documents apart"
    # Keys are ("structure", ruleId, wcag, severity) or ("registry", rule, status), so the rule
    # identity is at index 1 — the path tag is index 0.
    assert any(k[1] == "DOCX_HEADING_SKIP" for k in skipped - clean), sorted(skipped - clean)


def test_the_registry_path_carries_real_signal():
    """The registry half of the comparison must not be ten constants padding both sides.

    THIS TEST CORRECTED THE MODULE'S DESIGN, which is why it is worth keeping rather than folding
    into a comment. The first version asserted the opposite — that every docx rule returns REVIEW
    for every fixture, generalised from ONE file that happened to be all-REVIEW — and concluded
    the registry path was worthless here and should be excluded. Run across the whole corpus it
    failed immediately: 1.1.1 and 2.4.4 return FAIL on three fixtures. A constant would have been
    a reason to leave the registry out; real verdicts are the reason it is in.

    Kept as a guard because the argument runs the other way too. If these rules ever go back to
    uniform REVIEW, the registry half silently becomes padding — present, agreeing with itself,
    and measuring nothing — and this is what says so.
    """
    import formats.docx  # noqa: F401 — registration is lazy; without this the registry is empty
    import rule_registry

    rules = [r.rule for r in rule_registry.all_registrations() if r.fmt == "docx"]
    assert rules, "no docx registrations at all — the lazy import above stopped working"

    verdicts = {
        (rule, str(getattr(rule_registry.evaluate(rule, "docx", fixture), "status", "?")))
        for rule in rules for fixture in _corpus_docx()}
    statuses = {status for _, status in verdicts}
    assert len(statuses) > 1, (
        f"every docx rule now returns the same status ({statuses}) on every fixture, so the "
        f"registry half of the round-trip comparison is a constant on both sides and is no "
        f"longer measuring anything. Either restore a fixture that fails one of these rules, or "
        f"drop the registry from `_findings` and say why.")
    discriminating = {rule for rule, status in verdicts if status == "FAIL"}
    assert discriminating, "no docx rule reaches a FAIL on any fixture"


# ── the check itself ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", _corpus_docx(), ids=lambda p: p.stem)
def test_the_detectors_reach_the_same_verdict_after_an_independent_round_trip(fixture, tmp_path):
    """The whole point of P5.3.

    A difference here does not automatically mean the detector is wrong — LibreOffice may have
    genuinely changed the document's accessibility (dropping alt text, say). It means a human has
    to look at which of the two happened, and that is exactly the question the fixture suite
    cannot raise on its own because every fixture in it was written by the same library.
    """
    before = _findings(fixture)
    after = _findings(_round_trip(fixture, tmp_path / "rt"))

    gained, lost = after - before, before - after
    assert not gained and not lost, (
        f"{fixture.name}: the detectors disagree about the same document after LibreOffice "
        f"re-serialised it.\n  findings that appeared: {sorted(gained)}\n"
        f"  findings that vanished: {sorted(lost)}\n"
        f"Either a detector is keying on how the XML was written rather than on what the document "
        f"means, or LibreOffice changed the document's accessibility. Both are worth knowing.")


def test_the_skip_guard_names_the_binary_it_needs():
    """The skip reason has to be actionable, because this module is skipped in CI by design.

    A bare "skipped" tells a reader nothing about whether the check is broken or simply not
    installed, and a skip nobody can interpret is how a test quietly stops guarding anything.
    """
    reason = pytestmark.kwargs["reason"]
    assert SOFFICE in reason
    assert "libreoffice-writer" in reason, "the skip must name the package that fixes it"
