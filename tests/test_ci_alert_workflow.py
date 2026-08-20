"""A skipped deploy is silent, so something has to say it out loud.

On 2026-08-20 CI failed on main at 22:30 and nothing announced it. deploy.yml gates on
`workflow_run.conclusion == 'success'`, so every deploy afterwards resolved to SKIPPED — a grey
tick, not a red cross, indistinguishable from "nothing to do". Six commits landed over the next
hour, each pushed by someone who watched their own push succeed, and production stayed on the
22:25 build. It was found by the owner opening the app and asking where the work had gone.

ci-alert.yml opens (and closes) a single GitHub issue tracking whether main can ship. These cases
pin the properties that arrangement depends on, because every one can be undone by an edit that
looks like tidying:

  · the trigger drifting from deploy.yml's  → the alert stops covering the runs that gate shipping
  · losing `issues: write`                  → the workflow runs and writes nothing
  · `cancel-in-progress: true`              → two close-together runs race, and the LAST verdict
                                              (the one that should win) is the one cancelled
  · closing on `cancelled`                  → main is marked shippable on a run that never finished
  · filing a new issue per failure          → a log instead of a state mirror; six entries per
                                              outage, which teaches people to skim past it
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WF / name).read_text())


def _on(doc):
    # PyYAML parses a bare `on:` key as the boolean True (YAML 1.1), which is why this is not
    # simply doc["on"]. A test that silently KeyError'd here would be reported as a broken test
    # rather than as the drift it is meant to catch.
    return doc.get("on", doc.get(True))


@pytest.fixture(scope="module")
def alert():
    return _load("ci-alert.yml")


def test_it_exists_and_parses(alert):
    assert alert, "ci-alert.yml must parse as YAML"


def test_the_trigger_mirrors_the_one_that_gates_deploys(alert):
    """The alert must fire on EXACTLY the runs deploy.yml gates on.

    Not "a similar trigger" — the same one. If deploy.yml starts gating on a different set of runs
    and this does not follow, the gap between them is precisely the set of failures that block
    shipping without announcing it, which is the outage this file is named after.
    """
    a, d = _on(alert)["workflow_run"], _on(_load("deploy.yml"))["workflow_run"]
    assert a["workflows"] == d["workflows"] == ["CI"]
    assert a["types"] == d["types"] == ["completed"]
    # branches filters on the TRIGGERING run's head branch, so this is what keeps a red PR — which
    # blocks nothing that ships — from opening an issue claiming main cannot deploy.
    assert a["branches"] == d["branches"] == ["main"]


def test_it_can_actually_write_the_issue(alert):
    perms = alert["permissions"]
    assert perms.get("issues") == "write", "without this the workflow runs and writes nothing"


def test_close_together_runs_serialise_and_the_last_verdict_wins(alert):
    c = alert["concurrency"]
    assert c["group"], "two runs must not race to open two issues"
    # Deliberately the OPPOSITE of monitor.yml, and for the opposite reason: cancelling is safe
    # there because the job changes nothing. Here the newest completion carries the verdict that
    # should stand, so it must be allowed to finish.
    assert c["cancel-in-progress"] is False


def test_only_success_closes_it(alert):
    """`cancelled` and `skipped` are not evidence main is fixed.

    Closing on either would mark the repo shippable on the strength of a run that never produced a
    result — the same false-green shape the suite's other guards exist to prevent.
    """
    src = (WF / "ci-alert.yml").read_text()
    assert "if (conclusion === 'success')" in src
    assert "conclusion !== 'failure' && conclusion !== 'timed_out'" in src


def test_a_dispatch_with_no_run_asserts_nothing(alert):
    """Manual dispatch has no triggering run, so there is no conclusion to act on.

    Inventing a failure there would file an issue claiming main is broken on no evidence.
    """
    assert "if (!conclusion)" in (WF / "ci-alert.yml").read_text()


def test_one_outage_is_one_issue(alert):
    """A state mirror, not a log.

    Found by a stable marker in the BODY rather than by matching the title, because the title is
    prose and someone will reasonably edit it. Six red runs from one outage must update one issue.
    """
    src = (WF / "ci-alert.yml").read_text()
    assert "acp:ci-red-on-main" in src
    assert "issues.update" in src, "an existing issue is updated in place"
    assert "state: 'closed'" in src, "and closed again when main goes green"


def test_the_embedded_script_actually_parses():
    """A syntax error in the github-script body surfaces only when the workflow RUNS.

    Which is during an outage — the one moment the alert has to work. YAML validity says nothing
    about the JavaScript inside a block scalar, so the body is extracted and syntax-checked.

    Wrapped in an async function first: github-script executes the body inside one, so the
    top-level `await`s here are legal in that context and would be a syntax error in a bare file.
    Checking it unwrapped would fail on correct code.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available to syntax-check the embedded script")

    doc = _load("ci-alert.yml")
    script = doc["jobs"]["alert"]["steps"][0]["with"]["script"]
    assert "MARKER" in script, "extracted the wrong block"

    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as fh:
        fh.write(
            "const github={}, context={repo:{}}, core={}, process={env:{}};\n"
            "async function __wrap(){\n" + script + "\n}\n"
        )
        path = fh.name

    proc = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"embedded script is not valid JavaScript:\n{proc.stderr}"
