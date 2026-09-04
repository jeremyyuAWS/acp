"""Guards on .github/workflows/remediation-evals.yml — the one workflow that spends money.

Every assertion here is a decision someone made once and should have to make again deliberately:
the job is dispatch-only, it refuses candidates a runner cannot honestly measure, it checks for
the key before spending rather than after, and it always passes a spend cap. None of these fail
loudly in production if they regress — a `push:` trigger added by habit just quietly bills the
account on every commit — which is why they are pinned here rather than in a comment.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")     # declared in tests/requirements.txt

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "remediation-evals.yml"


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(wf: dict) -> dict:
    # PyYAML resolves a bare `on:` key to the boolean True (the Norway problem's cousin), so a
    # test that reads wf["on"] passes vacuously on a file that has no triggers at all.
    return wf.get("on", wf.get(True, {}))


def test_the_paid_job_can_only_be_started_by_a_human():
    wf = yaml.safe_load(WORKFLOW.read_text())
    triggers = _triggers(wf)
    assert set(triggers) == {"workflow_dispatch"}, (
        "every call this job makes is billed: a push/pull_request/schedule trigger would spend "
        "money on every commit and turn CI red on a vendor outage. Adding one is a decision, "
        "not a tidy-up.")


def test_it_always_passes_a_spend_cap(wf):
    steps = wf["jobs"]["evals"]["steps"]
    runner = next(s for s in steps if s.get("name") == "Run the evals")
    assert "--max-spend-usd" in runner["run"]
    assert "max_spend_usd" in _triggers(wf)["workflow_dispatch"]["inputs"]


def test_it_refuses_local_model_candidates(wf):
    """No Ollama server runs on a GitHub runner. Without this the report would show a candidate
    with 100% unusable output and read as a measurement of the model."""
    steps = wf["jobs"]["evals"]["steps"]
    guard = next(s for s in steps if "Reject candidates" in s.get("name", ""))
    assert "ollama:" in guard["run"] and "exit 1" in guard["run"]
    names = [s.get("name", "") for s in steps]
    assert names.index(guard["name"]) < names.index("Run the evals")


def test_the_key_is_checked_before_it_is_spent(wf):
    steps = wf["jobs"]["evals"]["steps"]
    names = [s.get("name", "") for s in steps]
    check = next(s for s in steps if "Check the keys" in s.get("name", ""))
    assert "ANTHROPIC_API_KEY" in check["env"]
    assert names.index(check["name"]) < names.index("Run the evals")


def test_a_cancelled_paid_run_is_the_worst_outcome_so_it_does_not_cancel(wf):
    assert wf["concurrency"]["cancel-in-progress"] is False
    assert wf["permissions"] == {"contents": "read"}


def test_the_report_survives_a_gate_failure(wf):
    """--fail-on-gate is exactly when someone wants to read the table."""
    for name in ("Put the report on the run summary", "Upload the report"):
        step = next(s for s in wf["jobs"]["evals"]["steps"] if s.get("name") == name)
        assert step.get("if") == "always()"


# ── the CLI half of the same guard ───────────────────────────────────────────────────────────

def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "run_remediation_evals.py"),
                           *args], capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_estimate_only_prices_the_run_without_calling_anything():
    r = _cli("--estimate-only", "--repeats", "3", "-c", "anthropic:claude-opus-5")
    assert r.returncode == 0
    assert "300 calls" in r.stderr and "$3.6000" in r.stderr


def test_the_spend_cap_refuses_before_the_first_call():
    r = _cli("--repeats", "3", "-c", "anthropic:claude-opus-5", "--max-spend-usd", "1.00")
    assert r.returncode == 2, "an over-budget run must not start"
    assert "refusing to start" in r.stderr


def test_a_free_run_is_quoted_too_rather_than_being_silent():
    r = _cli("--estimate-only", "--repeats", "1", "-c", "rules-only")
    assert r.returncode == 0 and "rules-only" in r.stderr and "$0.0000" in r.stderr
