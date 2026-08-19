"""An apt outage must cost you the OCR criteria — never the whole suite's signal.

`Install tesseract (OCR)` exists to turn coverage ON: ocr.is_available() gates 1.4.5 and 1.4.9,
and every test driving them self-skips without the binary. Its own comment says a gate silently
missing two criteria "is the shape of check this repo has been bitten by twice", so the job must
stay RED when tesseract is missing. That is not up for negotiation and nothing here softens it.

What changed on 2026-08-19 is where the job dies. The mirror degraded mid-afternoon — at 15:29
three of four shards installed tesseract in 1m50s-3m15s and one failed; by 15:49 all four failed
— and because the step exited 1, the suite never ran at all. Two PRs sat red with zero
information about the change under review.

So the install records its failure and the suite runs; a final step fails the job. Same colour,
useful contents. These cases pin the four things that arrangement depends on, because each can
be undone by a plausible edit that looks like tidying:

  · remove `continue-on-error` → back to a dead job with no test signal
  · remove the final step      → OCR loss becomes SILENT, which is strictly worse than before
  · move it before the suite   → the suite stops running again
  · drop `always()`            → a run that also has test failures quietly regains the OCR gap

Asserted against the workflow TEXT rather than a parsed tree: PyYAML is in neither
api/requirements.txt nor tests/requirements.txt, and adding a dependency to test a config file
is a worse trade than a handful of regexes. Same technique as the repo's other wiring tests.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"

pytestmark = pytest.mark.skipif(not CI.exists(), reason="needs .github/workflows/ci.yml")


@pytest.fixture(scope="module")
def ci() -> str:
    return CI.read_text()


def test_the_install_step_records_its_failure_instead_of_ending_the_job(ci):
    """Without this the suite never runs, and a red job says nothing about the change."""
    step = ci.split("- name: Install tesseract (OCR)", 1)[1].split("- name:", 1)[0]
    assert "id: tesseract" in step, "the step has no id, so nothing downstream can read its outcome"
    assert re.search(r"continue-on-error:\s*true", step), \
        "the install still ends the job at the apt failure, so no tests run"


def test_a_later_step_still_fails_the_job(ci):
    """The whole point is that the colour does not change. Losing this makes OCR loss silent."""
    assert "- name: Fail if OCR coverage was lost" in ci, \
        "nothing fails the job when tesseract is missing — 1.4.5/1.4.9 would be dropped silently"
    step = ci.split("- name: Fail if OCR coverage was lost", 1)[1]
    assert "steps.tesseract.outcome != 'success'" in step, \
        "the gate does not read the install step's real outcome"
    assert re.search(r"^\s*exit 1\s*$", step, re.M), "the gate does not actually fail the job"


def test_the_gate_runs_after_the_suite(ci):
    """Ordering IS the feature. Before the suite, this is just the old dead job again."""
    suite = ci.index("- name: Backend suite (shard")
    gate = ci.index("- name: Fail if OCR coverage was lost")
    assert suite < gate, \
        "the OCR gate runs before the suite, so the tests never execute during an outage"


def test_the_gate_fires_even_when_the_suite_also_failed(ci):
    """A run with both problems must not report only the test failures.

    Without always(), a failing suite short-circuits this step and the run goes red for the
    tests alone — reporting nothing about the missing OCR coverage, which is the silent gap.
    """
    step = ci.split("- name: Fail if OCR coverage was lost", 1)[1].split("run:", 1)[0]
    assert "always()" in step, "the gate is skipped when an earlier step failed"


def test_the_guards_and_the_suite_are_not_conditioned_on_the_install(ci):
    """They must run during an outage — that is the signal this change exists to preserve."""
    body = ci.split("- name: Install tesseract (OCR)", 1)[1]
    body = body.split("- name: Fail if OCR coverage was lost", 1)[0]
    for step in ("Backend suite (shard", "Matrix guard — capability ceiling still derivable",
                 "Backlog guard — docs/TODO.md coverage block is current",
                 "Matrix guard — rule changes declare their matrix impact"):
        assert step in body, f"{step!r} no longer sits between the install and the gate"
        after = body.split(step, 1)[1].split("- name:", 1)[0]
        assert "steps.tesseract" not in after, \
            f"{step!r} was made conditional on the tesseract install — it would stop running"
