"""The four capability levels stay four, and each keeps its own denominator.

WHAT THIS PROTECTS. `gen_capability_levels.py` exists because one number could not carry the
difference between "a detector is registered" and "a scan reports it" — a difference this repo has
now paid for four times. The pressure on such a report is always to collapse it back into one
figure, and the ways that happens are all quiet:

  * a level starts re-deriving a fact another report already owns, and the two drift apart;
  * `unverified` gets folded into one of the other two, turning "nobody looked" into an answer;
  * the denominators get mixed, so a count over 17 write lanes is read against 62 preset pairs;
  * a disproven cell keeps being counted as capability somewhere else.

Each is asserted below.

THE DRIFT ONE ALREADY HAPPENED, before this file existed. The first `tested_pairs()` re-derived
declarations from each generator's `DECLARED` tuple and reported 36 of 62 where
`gen_fixture_coverage` reported 51 — `gen_sc_corpus` (.docx) has no such tuple, and its fifteen
pairs simply vanished. Two reports disagreeing about one fact is precisely what a four-level
report is supposed to make impossible, so the delegation is asserted here rather than trusted.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gcl = _load("gen_capability_levels")


# ── the levels stay separate ─────────────────────────────────────────────────────

def test_every_level_states_its_own_denominator():
    """The mixing failure. A count over 17 write lanes read against 62 preset pairs is how a
    number stops meaning anything, so every level carries the denominator it was counted on."""
    d = gcl.levels()
    for level in ("registered", "reachable", "tested", "remediation_verified"):
        assert d[level].get("denominator"), f"{level} reports a count with no denominator"
    assert d["tested"]["of"] != d["remediation_verified"]["of"], (
        "tested and remediation-verified now share a denominator — if that is real, say why; "
        "they count different things over different populations")


def test_the_report_never_prints_a_single_combined_figure():
    """The collapse failure, guarded at the output. A reader who wants one number will invent one
    if the report offers a total, so it must not."""
    text = gcl._report(gcl.levels()).lower()
    for banned in ("total", "overall score", "combined"):
        assert banned not in text, f"the report now prints a {banned!r} — the four are not addable"
    assert "not a compliance measure" in text, (
        "the report no longer says what it is not — that sentence is the one that stops 'tested' "
        "being read as conformance")


def test_tested_is_delegated_not_re_derived():
    """The drift failure, and the one that already happened: re-deriving declarations reported 36
    where gen_fixture_coverage reported 51, because .docx keeps its declarations somewhere a naive
    getattr does not look. One implementation, asserted equal."""
    gfc = _load("gen_fixture_coverage")
    expected = sum(len(row["covered"]) for row in gfc.coverage().values())
    assert gcl.levels()["tested"]["count"] == expected, (
        "gen_capability_levels and gen_fixture_coverage disagree about how many pairs are tested — "
        "they must not have two implementations of one fact")


def test_the_tested_denominator_is_the_shipped_preset_and_says_it_is_not_compliance():
    d = gcl.levels()["tested"]
    assert d["of"] == len(gcl.preset_pairs())
    assert "not compliance" in d["denominator"].lower()


# ── unverified is a state, not a rounding ────────────────────────────────────────

def test_unverified_exists_and_is_reported_separately():
    """Folding `unverified` into proven would overstate; folding it into disproven would
    understate. It is neither, and it is the majority state for cells outside the corpus."""
    r = gcl.levels()["reachable"]
    assert r["unverified"], (
        "nothing is unverified — either every cell now has evidence (say so and delete this) or "
        "the state was collapsed into another")
    assert set(r["proven"]).isdisjoint(r["unverified"])
    assert set(r["disproven"]).isdisjoint(r["unverified"])


def test_a_disproven_cell_is_never_also_counted_as_proven():
    """The four cells this report was built for. A cell shown NOT to reach a scan must not appear
    in the proven set, whatever any other source says about it."""
    r = gcl.levels()["reachable"]
    assert set(r["disproven"]).isdisjoint(r["proven"]), (
        f"a disproven cell is also counted proven: {set(r['disproven']) & set(r['proven'])}")


def test_every_disproven_cell_names_a_test_file_that_exists():
    """An escape hatch that cites nothing is an assertion. Each entry must point at the test that
    established it, and that file must be there."""
    for pair, why in gcl.DISPROVEN.items():
        assert "tests/" in why, f"{pair} gives no test as evidence: {why}"
        named = why.split("tests/")[1].split()[0].rstrip(".,;—")
        assert (ROOT / "tests" / named).exists(), (
            f"{pair} cites tests/{named}, which does not exist — if the test was renamed or "
            f"removed, re-establish the finding before keeping the entry")


# ── remediation-verified means the document was checked, not the applier ─────────

def test_every_verified_lane_names_a_test_that_exists():
    """The count is only worth reading if each entry cites something. An escape hatch citing
    nothing is just an assertion, so the file it names has to be on disk."""
    d = gcl.levels()["remediation_verified"]
    assert d["count"] == len(gcl.REMEDIATION_VERIFIED)
    assert d["of"] == len(gcl.write_lanes()) and d["of"] > 0
    for (sc, fmt), why in gcl.REMEDIATION_VERIFIED.items():
        named = [w for w in why.split() if w.startswith("tests/") and w.endswith(".py")]
        assert named, f"{sc} {fmt} claims remediation-verified without naming a test: {why!r}"
        for path in named:
            assert (ROOT / path).exists(), f"{sc} {fmt} names {path}, which does not exist"


def test_a_verified_lane_may_not_rest_on_a_simulated_rescan():
    """THE bar, made mechanical rather than promised.

    The distinction this level exists to draw is between "the applier returned without raising"
    and "the saved document was re-opened and the criterion was gone". Every apply test in the
    repo except the ones cited here patches `_verify_residual_scs` and hands the lane its answer
    (`residual=set()`), which asserts what the lane does GIVEN a clean re-scan and says nothing
    about whether a re-scan of those bytes would be clean.

    So a cited test that patches the re-scan is not evidence of what it is being cited for, and
    this fails rather than trusting the entry's prose. Written as a check on the CITED file
    specifically: patching it elsewhere is normal and fine.

    Parsed, not grepped, and the difference was not hypothetical — the first version scanned raw
    lines and failed immediately on the cited file, because that file's own docstring QUOTES the
    `monkeypatch.setattr(handlers, "_verify_residual_scs", …)` line from
    tests/test_apply_approved_values.py to explain what it is doing differently. A guard that
    cannot tell a patch from a description of one would be answered by deleting the explanation,
    which is the opposite of what should happen."""
    import ast

    for (sc, fmt), why in gcl.REMEDIATION_VERIFIED.items():
        for path in [w for w in why.split() if w.startswith("tests/") and w.endswith(".py")]:
            tree = ast.parse((ROOT / path).read_text(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if not (isinstance(fn, ast.Attribute) and fn.attr in ("setattr", "setitem")):
                    continue
                names = {a.value for a in ast.walk(node) if isinstance(a, ast.Constant)
                         and isinstance(a.value, str)}
                names |= {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
                if "_verify_residual_scs" in names or "verify_residual_scs" in names:
                    raise AssertionError(
                        f"{sc} {fmt} is claimed remediation-verified on {path}, but that file "
                        f"patches the re-scan it is cited for, at {path}:{node.lineno}")


def test_the_write_lanes_come_from_handlers_not_from_a_list_here():
    """Restating the lanes would let this report claim a writer that does not exist. Asserted by
    checking a lane handlers.py declares and one it does not."""
    lanes = gcl.write_lanes()
    assert ("1.3.3", "docx") in lanes, "the sensory lane vanished — re-check the parse"
    assert ("3.1.2", "xlsx") not in lanes, (
        "xlsx is claimed for the 3.1.2 write lane, but SpreadsheetML has no run-level language "
        "element — handlers._LANGUAGE_EXTS excludes it on purpose")


# ── the report is readable and machine-readable ──────────────────────────────────

def test_json_mode_carries_every_level(capsys):
    import json
    assert gcl.main(["--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert set(d) == {"registered", "reachable", "tested", "remediation_verified"}
    assert set(d["reachable"]) >= {"proven", "disproven", "unverified"}


def test_the_text_report_names_each_disproven_cell(capsys):
    """A count of four teaches nobody which four."""
    assert gcl.main([]) == 0
    out = capsys.readouterr().out
    for sc, fmt in gcl.DISPROVEN:
        assert f"{sc} {fmt}" in out, f"{sc} {fmt} is counted but not named in the report"
