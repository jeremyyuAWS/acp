"""The 17-lane milestone states the engine condition it was measured under.

THE PROBLEM. "REMEDIATION-VERIFIED 17 of 17" was the same string in two situations that prove
materially different things:

  * CI, where ci.yml builds the .NET Office analyser and the 15 Office lanes are verified by a
    REAL re-scan of the written document.
  * A developer box with no .NET SDK, where `tests/conftest.py` installs a stand-in so the lanes
    can run at all — because fail-closed verification correctly refuses to credit a scan that no
    engine graded.

The stand-in is legitimate and necessary: without it those proofs cannot execute off-CI, and
before the fail-closed change they passed on such a box only by accident (the residual was read
off `issues` while the failed status was discarded — the very defect that change fixed). What it
cannot do is establish that a REAL scan verifies the document. It exercises the caller. So the
report must not present the two runs identically, and now does not.

WHY A TEST AND NOT JUST THE PRINT. The failure this guards is a claim drifting loose from its
conditions — the same shape as the four DISPROVEN cells, which were registered, plausible, and
reported as capability until somebody ran the experiment. A report that silently omits its
engine condition is how a stand-in result gets quoted externally as a real-engine one.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

GEN = ROOT / "scripts" / "gen_capability_levels.py"


def _report() -> str:
    r = subprocess.run([sys.executable, str(GEN)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, f"generator failed: {r.stderr[-2000:]}"
    return r.stdout


def _lanes() -> list:
    r = subprocess.run([sys.executable, str(GEN), "--json"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, f"generator --json failed: {r.stderr[-2000:]}"
    return json.loads(r.stdout)["remediation_verified"]["lanes"]


def test_the_split_between_engine_dependent_and_in_process_lanes():
    """15 Office lanes need the .NET analyser to grade a re-scan trustworthy; 2 pdf lanes run
    in-process (pikepdf) and are engine-independent on any host. If a lane is added, this fails
    until the split is restated — which is the point, since a new Office lane inherits the
    engine condition and a new pdf one does not."""
    lanes = _lanes()
    office = [l for l in lanes if not l.endswith(" pdf")]
    inproc = [l for l in lanes if l.endswith(" pdf")]
    assert len(lanes) == 17, f"the lane set changed ({len(lanes)}); restate the engine split"
    assert len(office) == 15, f"expected 15 Office lanes, got {len(office)}: {office}"
    assert sorted(inproc) == ["1.1.1 pdf", "4.1.2 pdf"], inproc


def test_the_report_always_states_which_condition_produced_the_number():
    """Whichever way the host is configured, the count is accompanied by its condition."""
    out = _report()
    assert "REMEDIATION-VERIFIED" in out
    assert "engine condition" in out, (
        "the milestone printed its count with no engine condition — a stand-in result is now "
        "indistinguishable from a real-engine one in this report")
    assert "THIS RUN:" in out


def test_a_standin_run_is_never_reported_as_real_engine_evidence():
    """THE GUARD. The two branches must say opposite things, and the absent branch must say
    plainly that it is not evidence — not merely omit the claim."""
    import engines
    out = _report()
    if engines.OFFICE_OK:
        assert "Office analyser PRESENT" in out
        assert "real-engine results" in out
        assert "ABSENT" not in out
    else:
        assert "Office analyser ABSENT" in out
        assert "NOT evidence" in out, (
            "the absent branch must state that a stand-in run is not evidence that a real scan "
            "verifies the document, not just decline to claim it is")
        assert "PRESENT" not in out
        # and it must point at where the real evidence does come from
        assert "check_engines.py --require office" in out


def test_ci_cannot_silently_downgrade_to_the_standin():
    """The reason the CI evidence can be trusted at all. If the Office analyser failed to build
    on a runner, `engines.OFFICE_OK` would be False, conftest would install the stand-in, and
    the lane proofs would pass anyway — green CI on a downgraded claim.

    What stops that is a separate step: ci.yml runs `check_engines.py --require office,pdf,ocr`
    on EVERY shard with `if: always()`, so a missing engine reddens the shard whatever the tests
    did. This asserts that step is still there and still required, because the guarantee is
    entirely in the workflow, not in the tests."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "check_engines.py --require office,pdf,ocr" in ci, (
        "the engine-availability gate left ci.yml — without it, a runner that failed to build "
        "the Office analyser reports the lane proofs green against a stand-in")
    assert "dotnet build spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj" in ci, (
        "CI no longer builds the Office analyser, so no run produces real-engine evidence")


def test_the_standin_is_scoped_to_the_lane_proofs_only():
    """It must not leak into the tests that deliberately observe a missing engine — those assert
    the fail-closed behaviour, and a stand-in would make them assert the opposite."""
    conftest_src = (ROOT / "tests" / "conftest.py").read_text()
    assert 'name.startswith("test_remediation_verified_")' in conftest_src, (
        "the Office stand-in is no longer scoped by module name — check it cannot reach "
        "tests/test_verification_engine_missing.py, which needs the real (absent) engine")
    assert "if engines.OFFICE_OK:" in conftest_src, (
        "the stand-in no longer defers to a real analyser when one is present, so CI would "
        "verify the lanes against the stand-in instead of the engine it just built")


def test_the_engine_condition_is_actually_DETERMINABLE():
    """THE BUG THIS TEST EXISTS FOR, and it was in the first draft of the feature above.

    `_office_analyser_present()` originally imported `engines` from api/ — it lives in tests/ —
    and swallowed the resulting ImportError as `office_ok = False`. Every branch still ran,
    every assertion above still passed, and the PRESENT branch was DEAD CODE: on CI, where the
    analyser IS built, the report would have said "ABSENT" and claimed the milestone rested on
    a stand-in. A wrong engine condition is worse than none, because it is quotable.

    Nothing caught it because the tests above ask which branch to expect from the SAME source
    the generator reads, so a source that always answers False agrees with itself. This asks a
    different question: can the condition be determined at all?
    """
    out = _report()
    assert "COULD NOT BE DETERMINED" not in out, (
        "the generator cannot read tests/engines.py, so its engine condition is a guess. That "
        "is the failure mode that made the PRESENT branch unreachable — fix the import rather "
        "than the message.")


def test_the_condition_is_read_from_the_module_that_decides_it_not_recomputed():
    """`scripts/check_engines.py` states the rule in its own header: 'A guard that recomputed
    the condition could pass while the tests it is guarding still skipped — which is the precise
    shape of a check that cannot fail.' The same applies here, and more sharply: conftest
    decides whether to install the stand-in from `engines.OFFICE_OK`, so anything else this
    report consults can disagree with what actually happened in the run it is describing."""
    src = GEN.read_text()
    assert 'ROOT / "tests"' in src, (
        "the engine condition no longer resolves tests/engines.py — if it now recomputes "
        "availability, it can disagree with the stand-in decision it claims to describe")
    assert "import engines" in src
    assert "engines.OFFICE_OK" in src
