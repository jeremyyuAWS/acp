"""The assessment scorer must have no numbers when it has no engine — not zeros.

THE BUG THIS PINS, measured on 2026-08-30. `scripts/score_assessment.py`'s `scan()` caught every
exception and returned `[], 0.0`. Zero findings is what a CLEAN document produces, so an engine
that never ran was indistinguishable from a document with nothing wrong — and on the four .docx
criteria that can certify, that resolves to PASS.

In a container without the .NET Office CLI, all 34 fixtures failed with
`FileNotFoundError: /root/.dotnet/dotnet` and the script printed:

    FALSE PASS  7 / 21  (33.3%)  — a real violation CERTIFIED as conformant.
    ...  table-no-header   1.3.1: FAIL->PASS

Every one of those numbers described a missing dependency. The per-fixture failures went to
stderr while the summary went to stdout, so a redirected run showed only the summary — a
scorecard with no surviving trace of the fact that nothing was scanned.

The product forbids exactly this of itself ("never convert an analyser error into a clean
result"). It was the measurement layer breaking the rule it exists to enforce, which is the worst
place for it: a false-PASS rate is the number someone would quote to decide whether ACP is
trustworthy.

`tests/test_docx_corpus_regression_gate.py::test_the_gate_actually_ran` already defended the
CI path with a coverage floor. These tests move the guarantee into the script, because the script
is also run by hand — and by hand is where a stripped environment is likeliest.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "score_assessment", ROOT / "scripts" / "score_assessment.py")
score_assessment = importlib.util.module_from_spec(_spec)
sys.modules["score_assessment"] = score_assessment
_spec.loader.exec_module(score_assessment)


def test_a_failed_scan_raises_instead_of_returning_zero_findings(monkeypatch, tmp_path):
    """The one-line inversion. `[], 0.0` made 'the engine is missing' and 'this document is
    clean' the same value."""
    import scanner
    doc = tmp_path / "x.docx"
    doc.write_bytes(b"PK\x03\x04not-a-real-docx")

    def _no_engine(*a, **kw):
        raise FileNotFoundError(2, "No such file or directory", "/root/.dotnet/dotnet")
    monkeypatch.setattr(scanner, "analyse_and_assess", _no_engine)

    with pytest.raises(score_assessment.ScanFailed) as e:
        score_assessment.scan(doc)
    # The message has to carry the remedy, or the next person re-derives it from a traceback.
    assert "did not run" in str(e.value)
    assert "check_engines" in str(e.value)


def test_a_working_scan_still_returns_its_findings(monkeypatch, tmp_path):
    """Fail-closed must not mean fail-always: the happy path is untouched."""
    import scanner
    doc = tmp_path / "x.docx"
    doc.write_bytes(b"PK\x03\x04not-a-real-docx")
    monkeypatch.setattr(scanner, "analyse_and_assess",
                        lambda *a, **kw: ({"issues": [{"rule_id": "1.1.1"}]}, None))
    issues, secs = score_assessment.scan(doc)
    assert [i["rule_id"] for i in issues] == ["1.1.1"]
    assert secs >= 0


def test_the_cli_refuses_before_scanning_when_the_office_engine_is_missing(monkeypatch, capsys):
    """Pre-flight, so the failure names the cause instead of arriving 34 fixtures later as an
    exception about a path — and so the refusal is impossible to mistake for a scorecard."""
    import check_engines
    monkeypatch.setitem(check_engines.CHECKS, "office", lambda: (False, "no dotnet here"))
    monkeypatch.setattr(sys, "argv", ["score_assessment.py", "--corpus", "/nonexistent"])

    assert score_assessment.main() == 2
    err = capsys.readouterr().err
    assert "cannot score" in err and "no dotnet here" in err
    # It must say WHY zeros would have been wrong, not just that a file is missing.
    assert "reads as PASS" in err
    # And it must not have produced a scorecard.
    assert "FALSE PASS" not in err


def test_the_cli_checks_the_engine_before_touching_the_corpus(monkeypatch, capsys):
    """The corpus path above is deliberately nonexistent: if the engine gate did not run first,
    this would fail on the missing directory instead, and the exit code would not distinguish
    'no engine' from 'no corpus'."""
    import check_engines
    scanned = []
    monkeypatch.setitem(check_engines.CHECKS, "office", lambda: (False, "no dotnet here"))
    monkeypatch.setattr(score_assessment, "score_corpus",
                        lambda *a, **kw: scanned.append(1) or {})
    monkeypatch.setattr(sys, "argv", ["score_assessment.py", "--corpus", "/nonexistent"])
    assert score_assessment.main() == 2
    assert scanned == [], "scoring started despite the engine being unavailable"


_gspec = importlib.util.spec_from_file_location(
    "run_docx_gates", ROOT / "scripts" / "run_docx_gates.py")
run_docx_gates = importlib.util.module_from_spec(_gspec)
sys.modules["run_docx_gates"] = run_docx_gates
_gspec.loader.exec_module(run_docx_gates)


def test_the_docx_gates_assess_raises_instead_of_reporting_no_criteria(monkeypatch, tmp_path):
    """The same inversion in the other tool that runs the scan path. `assess()` returned
    `set()` on failure, and Gate 3 — "assisted-only: assessed, not edited" — decides PASS from
    `n_edits == 0 and not dmg`, never consulting what was detected. So a run where nothing was
    assessed printed a NOTE and passed the gate anyway."""
    import scanner
    doc = tmp_path / "x.docx"
    doc.write_bytes(b"PK\x03\x04not-a-real-docx")
    monkeypatch.setattr(scanner, "analyse_and_assess", lambda *a, **kw: (_ for _ in ()).throw(
        FileNotFoundError(2, "No such file or directory", "/root/.dotnet/dotnet")))

    with pytest.raises(RuntimeError) as e:
        run_docx_gates.assess(doc)
    assert "Gate 3 would pass" in str(e.value)
    assert "check_engines" in str(e.value)


def test_the_docx_gates_refuse_to_start_without_the_engine(monkeypatch, capsys):
    import check_engines
    monkeypatch.setitem(check_engines.CHECKS, "office", lambda: (False, "no dotnet here"))
    monkeypatch.setattr(sys, "argv", ["run_docx_gates.py", "--root", "/nonexistent"])
    assert run_docx_gates.main() == 2
    err = capsys.readouterr().err
    assert "cannot run the gates" in err and "no dotnet here" in err


def test_latency_line_survives_a_corpus_that_scanned_instantly():
    """A cosmetic crash that mattered: with every scan failing, `sum(latencies)` was 0 and the
    summary died with ZeroDivisionError AFTER printing the false-PASS rate — so the run looked
    like a crash in reporting rather than a scorecard built on nothing, which is a much easier
    thing to dismiss as a script bug."""
    assert "if latencies and sum(latencies) > 0:" in \
        (ROOT / "scripts" / "score_assessment.py").read_text()
