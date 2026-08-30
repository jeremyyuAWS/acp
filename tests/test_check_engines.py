"""The engine fail-closed guard — scripts/check_engines.py.

A missing analysis engine degrades SILENTLY: the tests that need it self-skip, the suite goes
green, and the tick sits over criteria that were never exercised. ci.yml already refuses to let
that happen for OCR ("a green tick over a suite silently missing two criteria is precisely what
the install step was added to prevent"). This guard generalises that to all three engines and,
critically, to BOTH pipelines.

The tests below hold the properties that make the guard worth having rather than decorative:

  1. IT ACTUALLY FAILS. A guard whose failure path is never exercised is indistinguishable from
     one that always passes — this repo has shipped that exact shape before, in commands written
     to verify (`cmd | grep X || echo clean` printing "clean" when cmd never ran).
  2. IT ASKS THE SAME QUESTION THE SKIPS DO. The office/pdf answers come from tests/engines.py,
     the module whose OFFICE_OK / PDF_OK decide whether those tests skip. If the guard computed
     availability its own way, it could pass while the tests it guards still skipped.
  3. A BROKEN PROBE IS A MISSING ENGINE. If the availability check itself raises, that is not
     evidence of a working engine. Swallowing it as "unknown, carry on" turns a hard dependency
     failure back into the silent skip this exists to stop.
  4. BOTH PIPELINES CARRY IT. ci.yml's header calls step-for-step parity with azure-pipelines.yml
     "a live invariant, not a description" and records that it has already drifted once. It had
     drifted a second time when this landed: ci.yml had the OCR fail-closed step and
     azure-pipelines.yml did not, despite installing tesseract.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_engines", ROOT / "scripts" / "check_engines.py")
check_engines = importlib.util.module_from_spec(_spec)
sys.modules["check_engines"] = check_engines
_spec.loader.exec_module(check_engines)


# ── 1. the failure path is real ──────────────────────────────────────────────────

def test_a_missing_engine_fails_the_job(monkeypatch, capsys):
    monkeypatch.setitem(check_engines.CHECKS, "pdf", lambda: (False, "engine/pdf-analyser is gone"))
    assert check_engines.main(["--require", "pdf"]) == 1
    out = capsys.readouterr().out
    assert "::error::" in out                       # the GitHub Actions annotation
    assert "engine/pdf-analyser is gone" in out     # the remedy, not just the symptom
    # It names what went UNCHECKED, in criteria — the CI log's reader needs to know the cost,
    # not the module that failed to import.
    assert "PDF assessment" in out
    assert "read its result as partial" in out


def test_a_present_engine_passes(monkeypatch, capsys):
    monkeypatch.setitem(check_engines.CHECKS, "pdf", lambda: (True, ""))
    assert check_engines.main(["--require", "pdf"]) == 0
    assert "::error::" not in capsys.readouterr().out


def test_every_required_engine_is_reported_not_just_the_first(monkeypatch, capsys):
    """A run missing two engines must name both. Reporting only the first would send someone to
    install one dependency, re-run, and discover the next — one CI cycle at a time."""
    monkeypatch.setitem(check_engines.CHECKS, "office", lambda: (False, "no dotnet"))
    monkeypatch.setitem(check_engines.CHECKS, "ocr", lambda: (False, "no tesseract"))
    monkeypatch.setitem(check_engines.CHECKS, "pdf", lambda: (True, ""))
    assert check_engines.main([]) == 1
    out = capsys.readouterr().out
    assert "no dotnet" in out and "no tesseract" in out
    assert out.count("::error::") == 2


# ── 2 & 3. the probe is the same one the skips use, and a broken probe fails closed ──

def test_office_and_pdf_read_the_same_module_the_skips_do():
    """Not a mock: drives the real probes and asserts they agree with tests/engines.py. If the
    guard ever grows its own availability logic, this is what notices."""
    sys.path.insert(0, str(ROOT / "tests"))
    import engines
    assert check_engines._office()[0] is engines.OFFICE_OK
    assert check_engines._pdf()[0] is engines.PDF_OK
    # The remedy text is the same string the skip reason uses, so a developer reading either is
    # told the same thing.
    assert check_engines._office()[1] == engines.NO_OFFICE
    assert check_engines._pdf()[1] == engines.NO_PDF


def test_a_probe_that_raises_counts_as_missing(monkeypatch, capsys):
    def _boom():
        raise ModuleNotFoundError("no module named 'engines'")
    monkeypatch.setitem(check_engines.CHECKS, "pdf", _boom)
    assert check_engines.main(["--require", "pdf"]) == 1, (
        "a probe that raises must fail closed — an import that blows up is not evidence of a "
        "working engine")
    assert "probe itself failed" in capsys.readouterr().out


def test_report_mode_never_fails_and_covers_every_engine(capsys):
    """--report is for a human asking 'what have I got?', so it exits 0 even when engines are
    missing. It must still enumerate all three, or it would quietly under-report."""
    assert check_engines.main(["--report"]) == 0
    out = capsys.readouterr().out
    for name in check_engines.ENGINES:
        assert name in out


def test_an_unknown_engine_name_is_rejected(capsys):
    """A typo in a pipeline's --require must not silently check nothing. Exit 2, distinct from
    the 1 that means 'an engine is missing'."""
    assert check_engines.main(["--require", "pdff"]) == 2
    assert "unknown engine" in capsys.readouterr().err


def test_every_engine_has_a_coverage_line():
    """The error says what went unchecked; an engine with no COVERAGE entry would KeyError at
    exactly the moment the guard fires, turning a useful failure into a crash."""
    assert set(check_engines.COVERAGE) == set(check_engines.CHECKS) == set(check_engines.ENGINES)


# ── 4. both pipelines carry the gate ─────────────────────────────────────────────

CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
AZ = (ROOT / "azure-pipelines.yml").read_text()


@pytest.mark.parametrize("pipeline,src", [("ci.yml", CI), ("azure-pipelines.yml", AZ)],
                         ids=["ci.yml", "azure-pipelines.yml"])
def test_both_pipelines_run_the_guard(pipeline, src):
    assert "scripts/check_engines.py" in src, (
        f"{pipeline} does not run the engine guard. Two pipelines running one suite need the "
        f"same gates, or the suite means different things in each — ci.yml's header calls "
        f"step-for-step parity a live invariant, and it has now drifted twice.")


@pytest.mark.parametrize("pipeline,src", [("ci.yml", CI), ("azure-pipelines.yml", AZ)],
                         ids=["ci.yml", "azure-pipelines.yml"])
def test_the_guard_runs_after_the_suite(pipeline, src):
    """Deliberately LAST, for the reason ci.yml's OCR step already gives: dying at the install
    produces a red job carrying zero information about the change under review. Run the suite
    first, get the real pass/fail on everything that does not need the engine, then explain the
    red."""
    assert src.index("pytest tests/") < src.index("scripts/check_engines.py"), (
        f"{pipeline} runs the engine guard BEFORE the suite — a missing engine would then hide "
        f"every real result for the change under review")


@pytest.mark.parametrize("pipeline,src", [("ci.yml", CI), ("azure-pipelines.yml", AZ)],
                         ids=["ci.yml", "azure-pipelines.yml"])
def test_neither_pipeline_calls_the_pdf_engine_unvendored(pipeline, src):
    """The stale claim this guard was written for, and BOTH pipelines carried it independently.
    ADR 0029 vendored the engine; ci.yml's header said it was "NOT vendored" and that its suites
    skip, and azure-pipelines.yml went further and named two test modules as expected skips.
    tests/engines.py records being bitten by the identical stale claim once already.

    azure-pipelines.yml is the sharpest version: the paragraph directly above that block records
    the OFFICE comment outliving its constraint by three weeks and costing every CI run the
    engine-gated suites — and then the same thing happened to the other engine, in the same file,
    under the lesson.

    Asserts the AFFIRMATIVE rather than the absence of the old phrasing, deliberately: both files
    now quote that phrasing to explain what was wrong with it, and a test banning the substring
    would forbid the repo from recording its own history. What must hold is that the claim a
    reader takes away is the true one."""
    assert "vendored in engine/pdf-analyser/ since ADR 0029" in src, (
        f"{pipeline} no longer states that the PDF engine is vendored. A comment saying skipped "
        f"PDF suites are expected makes a checkout that really lost the engine look normal — "
        f"which is why the gap went unnoticed the first time")
