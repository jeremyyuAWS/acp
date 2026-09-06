"""Two runs on `main` must never share a concurrency group.

WHY THIS EXISTS. `deploy.yml` fires on `workflow_run: [CI] completed` and refuses anything whose
conclusion is not `success`. A CANCELLED run is neither success nor failure, so a cancelled CI run
on main means that commit never deploys -- silently, with a green-looking repository.

THE FIRST FIX WAS INCOMPLETE, AND THAT IS THE POINT. `cancel-in-progress: false` on main was
introduced to stop rapid merges cancelling each other, and its comment in `ci.yml` said the problem
was solved. It was not: a GitHub concurrency group holds one RUNNING run plus one PENDING run, and
a third arrival cancels the PENDING one regardless of `cancel-in-progress`, which governs only the
run already executing. Measured on 2026-09-06, twice inside ten minutes:

    CI 3545 (#1621), pending behind 3544 -- cancelled 20:56:11, as 3547 was created at 20:56:10
    CI 3549 (#1622), pending behind 3547 -- cancelled 21:06:58, as 3550 was created at 21:06:56

deploy run 1330 then refused main's tip -- "CI on b660a03 concluded 'cancelled', not success" --
and five merged PRs sat unshipped.

SO THIS TESTS THE RENDERED GROUP, NOT ITS SPELLING. Asserting that the expression contains
`github.sha` would pass for an expression that also applied the sha to pull requests, which would
break PR supersession instead. The invariant is about the VALUES two runs compute, so the
expression is evaluated against concrete contexts and the values compared.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"

MAIN = "refs/heads/main"
PULL = "refs/pull/1621/merge"


def _evaluate(expression: str, *, ref: str, sha: str) -> str:
    """Render one `${{ }}`-bearing workflow expression for a given context.

    DELIBERATELY NARROW. It covers the operators these two settings use and nothing else --
    `github.ref`, `github.sha`, `==`, `!=`, `&&`, `||`, `format()` and string literals -- and
    raises on anything it does not recognise rather than guessing. A general evaluator would be a
    second implementation of GitHub's language to get wrong; an unsupported operator here should
    fail loudly and be handled explicitly.

    GitHub's `&&` and `||` return operands rather than booleans, exactly like Python's `and`/`or`,
    and the empty string is falsy in both. That correspondence is what makes the translation below
    a substitution rather than an interpretation.
    """

    def render(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        allowed = re.fullmatch(r"[\w\s.'\-/{}(),!=&|]+", body)
        assert allowed, f"expression uses syntax this evaluator does not model: {body!r}"
        for token in ("? ", " : ", "[", "]"):
            assert token not in body, f"unsupported operator {token!r} in {body!r}"
        python = (
            body.replace("github.ref", repr(ref))
            .replace("github.sha", repr(sha))
            .replace("&&", " and ")
            .replace("||", " or ")
        )
        value = eval(python, {"__builtins__": {}}, {"format": lambda t, *a: t.format(*a)})  # noqa: S307
        if value is True:
            return "true"
        if value is False:
            return "false"
        return str(value)

    return re.sub(r"\$\{\{(.+?)\}\}", render, expression)


@pytest.fixture(scope="module")
def concurrency() -> dict:
    block = yaml.safe_load(CI.read_text())["concurrency"]
    assert "group" in block, "ci.yml has no concurrency group"
    return block


def group_for(concurrency: dict, *, ref: str, sha: str) -> str:
    return _evaluate(str(concurrency["group"]), ref=ref, sha=sha)


def test_two_commits_on_main_get_different_concurrency_groups(concurrency):
    """The whole fix. Same group => one waits for the other, and a third cancels the waiter."""
    first = group_for(concurrency, ref=MAIN, sha="b660a03a50fe1808b6b10754c753144df4acdaee")
    second = group_for(concurrency, ref=MAIN, sha="c1a0d27a29a275170a62f23b516385e5885dbc3f")
    assert first != second, (
        "two commits on main share a concurrency group, so a third merge will cancel whichever "
        "is pending and that commit will never deploy"
    )


def test_two_runs_on_one_pull_request_share_a_group(concurrency):
    """Keying every ref by sha would 'fix' main by breaking PR supersession instead.

    A PR's runs must collide so `cancel-in-progress` can retire the stale one; that is what keeps
    a ten-push branch from occupying ten runners.
    """
    first = group_for(concurrency, ref=PULL, sha="1111111111111111111111111111111111111111")
    second = group_for(concurrency, ref=PULL, sha="2222222222222222222222222222222222222222")
    assert first == second, (
        "two pushes to one pull request no longer share a group, so the superseded run keeps "
        "running instead of being cancelled"
    )


def test_a_main_group_is_never_also_a_pull_request_group(concurrency):
    """Distinct refs must stay distinct however the sha suffix is spelled."""
    assert group_for(concurrency, ref=MAIN, sha="a" * 40) != group_for(
        concurrency, ref=PULL, sha="a" * 40
    )


def test_only_pull_request_runs_are_cancelled_in_progress(concurrency):
    """Main keeps `false`. With one group per commit it has nothing in flight to cancel, and the
    flag is the wrong lever anyway -- that mistake is what this file exists to prevent recurring."""
    expression = str(concurrency["cancel-in-progress"])
    assert _evaluate(expression, ref=MAIN, sha="a" * 40) == "false"
    assert _evaluate(expression, ref=PULL, sha="a" * 40) == "true"


def test_deploy_still_requires_a_successful_ci_run():
    """The reason a cancelled run costs a deploy. If this condition ever stops demanding success,
    the cost of a shared group changes and this file's premise should be re-read, not assumed."""
    condition = yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["if"]
    assert "workflow_run.conclusion == 'success'" in condition.replace('"', "'"), (
        "deploy no longer gates on a successful CI run; re-derive why main needs one group per "
        "commit before trusting this test's rationale"
    )
