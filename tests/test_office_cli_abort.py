"""A crashed Office analyser must never certify a document.

The bug, from production Log Analytics on 2026-07-30: both .xlsx files in the estate logged

    [scan] office CLI exited -6:

on every run — SIGABRT, empty stderr — and still came out `analysed` with numeric scores
(2 findings on one, 5 on the other) and `compliant` true. `_analyse_office` printed the
returncode and then dropped it on the floor, building its result purely from `_o.json`. A
process that died was therefore indistinguishable from one that finished, which is the exact
failure mode #84, #86 and #101 each found somewhere else: the app knew and told nobody.

What makes the crash dangerous rather than merely noisy is AcpScan.Cli's write shape.
Program.cs accumulates every file's result and writes them in ONE `File.WriteAllText` after
the loop, so the abort's timing decides what survives:

  * after a complete write  -> parseable, complete-LOOKING output. Certified. The bug.
  * mid-write               -> truncated JSON; `json.loads` raised straight out of
                               `_analyse_office`, and `run_scan` guards its body with a bare
                               `finally`, so one crashed CLI failed the WHOLE scan.
  * before the write        -> no output; the caller's "no engine result" substitution already
                               bucketed these as engine-error. This case was always honest.

These tests pin all three, plus the clean path. They drive the scanner's real subprocess
plumbing with `tests/office_cli_abort_stub.py` standing in for the .dll — see that module for
why the native crash is not reproducible here, and `test_real_office_cli_exits_cleanly` below
for the check that the real analysers still exit 0.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))

import scanner  # noqa: E402
from engines import NO_OFFICE, OFFICE_OK  # noqa: E402
from rubric import Rubric  # noqa: E402

STUB = Path(__file__).resolve().parent / "office_cli_abort_stub.py"
REAL_XLSX = ACP / "demo-fixtures" / "excel-accessibility-demo.xlsx"


@pytest.fixture
def office_dir(tmp_path: Path) -> Path:
    """A one-file scan directory, matching the fan-out path's shape (ADR 0007)."""
    d = tmp_path / "scan"
    d.mkdir()
    (d / "book.xlsx").write_bytes(b"PK\x03\x04not-a-real-xlsx")
    return d


@pytest.fixture
def run_stub(monkeypatch):
    """Run `_analyse_office` with the crashing stub in place of the .NET CLI."""
    def _run(mode: str, dest: Path) -> dict:
        monkeypatch.setattr(scanner, "DOTNET", sys.executable)
        monkeypatch.setattr(scanner, "CLI_DLL", STUB)
        monkeypatch.setenv("ACP_STUB_MODE", mode)
        return scanner._analyse_office(dest)
    return _run


def assess(entry: dict | None) -> dict:
    """Rubric verdict for one engine result, including the caller's absent-result default.

    The default is copied from `analyse_and_assess` / `run_scan` deliberately: a file the CLI
    never reported is exactly what those two substitute for, and the test should assert on the
    verdict a scan would actually persist.
    """
    entry = entry or {"succeeded": False, "issues": [], "errors": ["no engine result"]}
    rb = Rubric.load_active(ACP / "config")
    return rb.assess(entry["succeeded"], entry["issues"], entry["errors"])


# ── the production case: complete output, then SIGABRT at runtime shutdown ─────────


def test_abort_after_complete_write_is_not_certifiable(office_dir, run_stub):
    """The regression proper. Findings survive; the certification does not."""
    res = run_stub("abort_after_complete_write", office_dir)
    a = assess(res.get("book.xlsx"))

    assert a["status"] == "uncertain", (
        "a CLI killed by SIGABRT scored the file as fully analysed — this is the production bug")
    assert a["compliant"] is False, "a document whose analyser crashed was certified"
    assert a["score_is_upper_bound"] is True, (
        "the score must read as a ceiling: the abort may have cut the rule sweep short")


def test_abort_after_complete_write_keeps_the_findings_it_did_produce(office_dir, run_stub):
    """`uncertain`, not `error` — the findings are real even though the set may be partial.

    Scoring these `error` would report "n/a (could not analyse)" for a run that produced 2 and
    5 findings in production, discarding true positives to describe the crash. The rubric
    already has the right vocabulary for "we have findings but cannot claim they are all of
    them", so the fix reaches for that instead of inventing a status.
    """
    res = run_stub("abort_after_complete_write", office_dir)
    entry = res["book.xlsx"]

    assert [i["ruleId"] for i in entry["issues"]] == ["xlsx.sheet-name", "xlsx.merged-cells"]
    assert assess(entry)["score"] == 90, "findings were dropped or re-penalised by the abort path"


def test_abort_is_recorded_as_a_process_error_not_a_rule_error(office_dir, run_stub):
    """`rule: None`, so per-rule attribution ignores it but skipped_rules still counts it.

    store.py's rule-status rollup keys off `e["rule"]` and skips errors without one, so a
    process-level abort must not name a rule — attributing SIGABRT to `xlsx.sheet-name` would
    mark that rule as erroring on the review page when it in fact returned findings.
    """
    res = run_stub("abort_after_complete_write", office_dir)
    added = [e for e in res["book.xlsx"]["errors"] if "SIGABRT" in e.get("message", "")]

    assert len(added) == 1, "the abort left no error behind, so nothing surfaces it"
    assert added[0]["rule"] is None
    assert assess(res["book.xlsx"])["skipped_rules"] == 1


def test_abort_names_the_signal(office_dir, run_stub):
    """-6 is SIGABRT, not "exit status 6". The log line and the error must say so.

    A negative returncode means killed-by-signal; rendering it as a status is what made the
    original log line ("office CLI exited -6") read as an application error code and sent the
    first look at this into the analysers rather than the runtime.
    """
    res = run_stub("abort_after_complete_write", office_dir)
    message = res["book.xlsx"]["errors"][-1]["message"]

    assert "SIGABRT" in message, message
    assert scanner._cli_exit_reason(-6) == "was killed by SIGABRT"
    assert scanner._cli_exit_reason(1) == "exited with status 1"


# ── the other two timings ──────────────────────────────────────────────────────────


def test_truncated_output_degrades_instead_of_failing_the_whole_scan(office_dir, run_stub):
    """A half-written `_o.json` must bucket as engine-error, not raise.

    `json.loads` on truncated JSON always throws — which is the one mercy here, since it means
    partial output can never be *parsed* as complete. But the throw escaped `_analyse_office`,
    and `run_scan`'s only handler is a `finally`, so a single crashed CLI took down every file
    in the scan including the PDFs it never touched.
    """
    res = run_stub("abort_after_truncated_write", office_dir)     # must not raise
    a = assess(res.get("book.xlsx"))

    assert res == {}, "unreadable output must not yield engine results"
    assert a["status"] == "error"
    assert a["score"] is None, "an unanalysable file carries no score (see #101)"
    assert a["compliant"] is False


def test_abort_before_write_is_an_engine_error(office_dir, run_stub):
    """The already-honest case, pinned so the fix does not regress it into a silent pass."""
    res = run_stub("abort_before_write", office_dir)
    a = assess(res.get("book.xlsx"))

    assert res == {}
    assert a["status"] == "error"
    assert a["score"] is None
    assert a["compliant"] is False


def test_timeout_with_output_already_written_is_also_uncertain(office_dir, run_stub, monkeypatch):
    """A CLI that wrote its findings and then hung is the timeout's version of the same trap.

    The timeout branch used to log "files will be recorded as engine-error", which is only true
    when nothing was written — `res` is built from `_o.json` regardless of how the process ended,
    so a hang *after* the write parsed as a clean run exactly like the SIGABRT did.
    """
    monkeypatch.setenv("ACP_OFFICE_CLI_TIMEOUT", "2")
    res = run_stub("write_then_hang", office_dir)
    a = assess(res.get("book.xlsx"))

    assert a["status"] == "uncertain"
    assert a["compliant"] is False
    assert "timed out after 2s" in res["book.xlsx"]["errors"][-1]["message"]


def test_clean_exit_is_unaffected(office_dir, run_stub):
    """The whole point is to separate a crash from a clean run, so the clean run must not move.

    Without this, marking every file uncertain would also "fix" the bug — and would make every
    Office scan in the estate permanently uncertifiable.
    """
    res = run_stub("clean", office_dir)
    a = assess(res.get("book.xlsx"))

    assert a["status"] == "analysed", "a clean CLI exit was penalised as if it had crashed"
    assert a["score"] == 90
    assert a["score_is_upper_bound"] is False
    assert a["skipped_rules"] == 0
    assert res["book.xlsx"]["errors"] == []


def test_every_reported_file_in_a_batch_is_marked(tmp_path, run_stub):
    """run_scan's batch path runs ONE CLI over the whole directory, so one abort taints all of it.

    Production saw this per-file (the fan-out path gives each file its own invocation), but the
    batch path shares a process: if it aborts, no file it reported can claim a complete sweep.
    """
    d = tmp_path / "batch"
    d.mkdir()
    for name in ("a.xlsx", "b.docx", "c.pptx"):
        (d / name).write_bytes(b"PK\x03\x04stub")

    res = run_stub("abort_after_complete_write", d)

    assert set(res) == {"a.xlsx", "b.docx", "c.pptx"}
    assert all(assess(e)["status"] == "uncertain" for e in res.values())
    assert all(assess(e)["compliant"] is False for e in res.values())


# ── and the real analysers, to keep the stub honest about the happy path ───────────


@pytest.mark.skipif(not OFFICE_OK, reason=NO_OFFICE)
def test_real_office_cli_exits_cleanly_on_a_real_xlsx(tmp_path):
    """The real CLI on a real .xlsx exits 0 here — which is why the crash needs a stub.

    This is the local half of the investigation, kept as a test: if the SIGABRT ever does
    become reproducible on a dev box or in CI, this is what will fail, and it fails with the
    actual returncode rather than a swallowed log line. It also guards the fix from the other
    direction — if `_analyse_office` ever started reporting clean runs as aborted, the estate
    would go uniformly uncertain and this catches it against the genuine analysers.
    """
    assert REAL_XLSX.exists(), f"missing demo fixture {REAL_XLSX}"
    shutil.copy(REAL_XLSX, tmp_path / REAL_XLSX.name)

    proc = subprocess.run(
        [scanner.DOTNET, str(scanner.CLI_DLL), str(tmp_path), str(tmp_path / "_o.json")],
        capture_output=True, text=True, timeout=300)

    assert proc.returncode == 0, (
        f"office CLI {scanner._cli_exit_reason(proc.returncode)} "
        f"({proc.returncode}) on {REAL_XLSX.name}: {proc.stderr[-2000:]}")

    a = assess(scanner._analyse_office(tmp_path).get(REAL_XLSX.name))
    assert a["status"] == "analysed", "a clean real-CLI run must not be reported as uncertain"
