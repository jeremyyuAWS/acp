"""Ground-truth fixture coverage, and the ratchet that stops it shrinking.

WHY A COVERAGE REPORT AT ALL. The Phase-1 acceptance criterion is "all applicable pairs have
explicit fixture coverage or a documented human-only rationale". Nothing computed that, so the
size of the remaining job was unknown — and an unknown denominator is how "we have a corpus"
becomes a claim nobody can check. The answer today is 47 of 62 (76%): .docx complete, and a
partial labelled corpus for each of xlsx, pptx and pdf. It started at 15 of 62 (24%), with
.docx the only format that had one at all.

COUNTING DECLARATIONS, NOT FILES. A fixture that happens to be a .docx says nothing about 1.4.3
unless it declares an expectation for 1.4.3. Counting files in a format would report coverage
that does not exist, which is the easy and wrong version of this script.

THE GUARD IS A RATCHET. `--check` fails on a DROP, not on falling short of 100%. A guard that is
red on every commit stops being read; docs/TODO.md's generated block went 387 commits stale for
exactly that class of reason and read as current the whole time. A ratchet is the version that
merges and still refuses to let a fixture quietly disappear.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "gen_fixture_coverage", ROOT / "scripts" / "gen_fixture_coverage.py")
gfc = importlib.util.module_from_spec(_spec)
sys.modules["gen_fixture_coverage"] = gfc
_spec.loader.exec_module(gfc)


# ── the denominator is the shipped preset, not a number typed here ───────────────

def test_the_applicability_model_is_the_shipped_preset():
    """62 pairs across 17 criteria — read from assessment_policy.SCOPE_PRESETS['acp-core-17'],
    which is a real product scope, not a filter invented by the report. If someone changes what
    ACP considers in scope, this number moves with it rather than lying."""
    pairs = gfc.applicable_pairs()
    total = sum(len(v) for v in pairs.values())
    assert total == 62, f"the preset now has {total} pairs — update BASELINE and this test together"
    assert set(pairs) == set(gfc.FORMATS)


def test_every_format_is_accounted_for():
    """A format missing from the report is worse than one reported at zero: zero is a number
    somebody can act on."""
    cov = gfc.coverage()
    assert set(cov) == set(gfc.FORMATS)
    for fmt in gfc.FORMATS:
        assert cov[fmt]["applicable"], f"{fmt} has no applicable pairs — the preset lost a format"


# ── coverage is counted from declarations ────────────────────────────────────────

def test_coverage_is_complete_for_docx_and_partial_for_the_other_three():
    """The honest state. gen_sc_corpus.py declares an expectation for every .docx pair in the
    preset; the other three corpora are deliberately partial, declaring only the pairs whose
    detector was actually driven against the fixture and confirmed to fire (see
    tests/test_xlsx_corpus.py, test_pptx_corpus.py, test_pdf_corpus.py). Every format now has a
    labelled corpus; none but .docx is complete, and the missing pairs are named by the report
    rather than rounded away.

    Most of those confirmations hold wherever the suite runs. Two — xlsx 2.4.2 and 3.1.1 — have
    no first-party detector on any Office format and are proven by the .NET analyser, so they
    hold in CI and not on a bare checkout. `engine_only` reports them separately, and the
    assertion below pins the split so it cannot widen without someone saying why.

    This assertion FAILED when each corpus landed, which is the guard working: it names the two
    things a new corpus has to do — join GENERATORS and raise its BASELINE — and refuses to pass
    until both are done and this line is updated to the new truth."""
    cov = gfc.coverage()
    assert cov["docx"]["missing"] == [], (
        f"a .docx pair lost its fixture: {cov['docx']['missing']}")
    assert cov["docx"]["has_generator"] is True

    assert cov["xlsx"]["has_generator"] is True
    assert len(cov["xlsx"]["covered"]) == 11, (
        f"the xlsx corpus now declares {len(cov['xlsx']['covered'])} pairs — raise "
        f"BASELINE['xlsx'] and this count together, in the commit that adds the fixtures")
    # Two of those ten (2.4.2, 3.1.1) are confirmed only where the .NET analyser is built. Pinned
    # here so the split cannot quietly widen: every pair that joins it weakens what the headline
    # number promises, and that should be a decision in a diff rather than a drift.
    assert cov["xlsx"]["engine_only"] == ["2.4.2", "3.1.1"], (
        f"the engine-only set is now {cov['xlsx']['engine_only']} — if that is deliberate, say "
        f"so here; the headline coverage number implies a guarantee these pairs do not have")

    assert cov["pptx"]["has_generator"] is True
    assert len(cov["pptx"]["covered"]) == 10, (
        f"the pptx corpus now declares {len(cov['pptx']['covered'])} pairs — raise "
        f"BASELINE['pptx'] and this count together, in the commit that adds the fixtures")

    assert cov["pdf"]["has_generator"] is True
    assert len(cov["pdf"]["covered"]) == 11, (
        f"the pdf corpus now declares {len(cov['pdf']['covered'])} pairs — raise "
        f"BASELINE['pdf'] and this count together, in the commit that adds the fixtures")


def test_every_format_now_has_a_labelled_corpus():
    """The state this report was written to make measurable, and the thing that changed: at 15
    of 62 only .docx had a generator at all. Asserted separately from the counts above so that
    losing a whole corpus reads as its own failure rather than as a number moving."""
    cov = gfc.coverage()
    for fmt in gfc.FORMATS:
        assert cov[fmt]["has_generator"] is True, f"{fmt} no longer has a labelled corpus"


def test_a_format_with_no_generator_is_distinguished_from_one_that_found_nothing(monkeypatch):
    """"Nobody has written a corpus" and "the corpus declares nothing" are different states, and
    only the first is answered by writing fixtures. Mapping an absent generator to an empty set
    would collapse them.

    Every format has a generator now, so this can no longer be shown with a real gap — it is
    shown by removing one, which is the same comparison and keeps the distinction tested rather
    than retired along with the last empty format."""
    cov = gfc.coverage()
    assert cov["pdf"]["has_generator"] is True
    assert cov["pdf"]["covered"] != []

    monkeypatch.delitem(gfc.GENERATORS, "pdf")
    gone = gfc.coverage()
    assert gone["pdf"]["has_generator"] is False
    assert gone["pdf"]["covered"] == []
    # The applicable list is unchanged — losing a corpus must not shrink the denominator too.
    assert gone["pdf"]["applicable"] == cov["pdf"]["applicable"]


def test_coverage_counts_declarations_not_files():
    """The corpus is ~34 .docx files but only 15 pairs; if this counted files the number would
    be nonsense. Asserted as an inequality so it survives fixtures being added."""
    cov = gfc.coverage()
    import gen_sc_corpus
    assert len(gen_sc_corpus.FIXTURES) > len(cov["docx"]["covered"]), (
        "more covered pairs than fixtures — coverage is being counted by file, not declaration")


# ── the ratchet ──────────────────────────────────────────────────────────────────

def test_check_passes_at_the_current_baseline(capsys):
    assert gfc.main(["--check"]) == 0
    assert "no regression" in capsys.readouterr().out


def test_check_fails_when_a_covered_pair_loses_its_fixture(monkeypatch, capsys):
    """The whole point of the guard. Simulated by raising the floor rather than deleting a
    fixture, which is the same comparison from the other side and does not require mutating the
    generator."""
    monkeypatch.setitem(gfc.BASELINE, "docx", 99)
    assert gfc.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "regressed" in err
    assert "baseline is 99" in err
    # It must name what to do, or the next person's options are "delete the guard".
    assert "lower" in err and "deliberately" in err


def test_the_baseline_matches_reality_so_the_ratchet_starts_armed(capsys):
    """A baseline BELOW actual coverage is a guard with slack in it — a fixture could be deleted
    and the check would still pass. Pins them equal, so the ratchet bites on the first loss."""
    cov = gfc.coverage()
    for fmt in gfc.FORMATS:
        assert gfc.BASELINE[fmt] == len(cov[fmt]["covered"]), (
            f"BASELINE[{fmt!r}] is {gfc.BASELINE[fmt]} but {len(cov[fmt]['covered'])} pairs are "
            f"covered — raise it in the commit that adds the fixtures, so the guard has no slack")


def test_both_pipelines_run_the_guard():
    """Added to both in the same commit. ci.yml's header calls step-for-step parity with
    azure-pipelines.yml "a live invariant, not a description", and it has drifted twice — the
    three matrix guards landing in one first, and the OCR fail-closed step (#1005). Adding a new
    guard to only one pipeline is how the third drift starts."""
    for name, path in (("ci.yml", ROOT / ".github" / "workflows" / "ci.yml"),
                       ("azure-pipelines.yml", ROOT / "azure-pipelines.yml")):
        assert "gen_fixture_coverage.py --check" in path.read_text(), (
            f"{name} does not run the corpus guard")


def test_json_mode_emits_the_whole_map(capsys):
    import json
    assert gfc.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == set(gfc.FORMATS)
    assert "missing" in data["pptx"] and "applicable" in data["pptx"]
