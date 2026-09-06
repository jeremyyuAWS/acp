"""Every CI job runs the Python the API image runs.

WHY THIS EXISTS. `ci.yml`'s Postgres integration job sat on 3.11 with no stated reason -- no
comment, nothing in the commit that introduced it (#1084) -- while every other job,
azure-pipelines.yml and the production image were on 3.12. So one job tested a version nothing
ships, which is the wrong kind of coverage: it can only produce failures that do not matter and
miss failures that do.

IT WAS NOT HYPOTHETICAL, AND THE WAY IT SURFACED IS THE POINT. #1592 added a nested-quote f-string
to api/routes/scans.py -- PEP 701 syntax, a SyntaxError before 3.12. CI stayed green, because that
job's test selection happens not to import that module. Nothing was wrong with the code and
nothing was wrong with the job; the two simply had not met yet. Adding a test to that job that
imported the app would have turned it red for a reason that had nothing to do with the test, and
whoever hit it would have spent the afternoon on their own change.

A DRIFTED PIN IS INVISIBLE UNTIL IT IS EXPENSIVE, which is why this is a test and not a comment.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_IMAGE = ROOT / "deploy" / "public" / "Dockerfile.base-api"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
AZURE_PIPELINE = ROOT / "azure-pipelines.yml"


def production_python() -> str:
    """The version the API container actually runs.

    Read from the Dockerfile rather than written here: a constant in this file would be a second
    place to update, and the failure mode of the two disagreeing is this test passing while every
    job runs the wrong version.
    """
    match = re.search(r"^FROM\s+\S*python:(\d+\.\d+)", API_IMAGE.read_text(), re.M)
    assert match, f"no python base image found in {API_IMAGE}"
    return match.group(1)


def _pins(path: Path) -> list[tuple[int, str]]:
    """(line number, version) for every Python pin in one YAML file.

    Comment lines are skipped and only 3.x values are taken: azure-pipelines.yml discusses
    `versionSpec` in prose about the Node task, and NodeTool's own versionSpec is a Node version.
    Matching either would make this test fail for a reason it is not about.
    """
    found = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = re.match(r"""(?:python-version|versionSpec):\s*['"]?(3\.\d+)['"]?\s*$""", stripped)
        if match:
            found.append((number, match.group(1)))
    return found


def test_the_production_python_is_readable():
    """The regex resolves to a version, whatever that version is.

    Deliberately NOT `== "3.12"`. This test is about the read still working, and pinning the value
    here would make a legitimate upgrade fail a test named "is readable" — which teaches the next
    person to edit the assertion rather than read it. The sweeps below are what hold the pins
    together; they follow production wherever it goes.
    """
    assert re.fullmatch(r"3\.\d+", production_python())


def test_every_workflow_pins_the_production_python():
    expected = production_python()
    drifted = [f"{path.relative_to(ROOT)}:{number} pins {version}"
               for path in WORKFLOWS
               for number, version in _pins(path)
               if version != expected]
    assert not drifted, (
        f"these CI jobs do not run the version the API image runs ({expected}): "
        + "; ".join(drifted))


def test_azure_pipelines_pins_the_production_python():
    expected = production_python()
    drifted = [f"{number} pins {version}" for number, version in _pins(AZURE_PIPELINE)
               if version != expected]
    assert not drifted, f"azure-pipelines.yml disagrees with the API image ({expected}): {drifted}"


def test_the_postgres_integration_job_is_covered():
    """The job that actually drifted, named explicitly.

    The sweep above would catch it, but only while the pin keeps its current spelling. This fails
    if the job stops being pinned at all -- setup-python without a version resolves to whatever
    the runner ships, which is the same drift with no line to point at.
    """
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = text.split("Postgres integration (schema/lock regressions)", 1)
    assert len(job) == 2, "the Postgres integration job was renamed; update this guard"
    after = job[1]
    setup = after.find("actions/setup-python")
    assert setup != -1, "the Postgres integration job no longer sets up Python explicitly"
    window = after[setup:setup + 200]
    assert f"python-version: '{production_python()}'" in window, window


@pytest.mark.parametrize("path", WORKFLOWS + [AZURE_PIPELINE], ids=lambda p: p.name)
def test_no_workflow_is_silently_unpinned(path: Path):
    """A file that sets up Python must say which.

    `actions/setup-python` with no version does not fail -- it installs the runner's default,
    which changes when GitHub changes it. That is drift nobody committed.
    """
    text = path.read_text()
    uses = text.count("actions/setup-python")
    if not uses:
        pytest.skip(f"{path.name} does not set up Python")
    assert len(_pins(path)) >= uses, (
        f"{path.name} calls setup-python {uses} time(s) but declares "
        f"{len(_pins(path))} version pin(s)")
