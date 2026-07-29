"""The matrix-impact guard must judge AUTHORED commits, and only those.

`scripts/gen_progress_log.py --check` fails a commit that touches rule code without a
`Matrix-Note:` trailer. On a pull request CI runs it over the GitHub MERGE ref, so the range
includes a merge commit — which authors nothing and has no message anyone could put a trailer
in. The workflow comment has always said merge commits are skipped; the implementation relied
on `git show --name-only` printing nothing for one.

That is only true when the two sides touched DISJOINT files. `git show` renders a merge as a
COMBINED diff — whatever differs from every parent — so a PR whose base branch edited the same
rule file produces a non-empty list, and CI flags GitHub's own merge ref for a trailer that
cannot exist. The PR then cannot go green by any action its author can take: rebasing hides it,
but nothing in the message can satisfy it.

Observed on PR #38, whose base and branch both edited api/remediate_pdf.py:

    14aa527 touches rule code but has no Matrix-Note: trailer
             Merge 12d4f61… into 356ad32…

These build real repositories rather than mocking git, because the bug lived entirely in what
git chooses to print for a merge — a mock would have reproduced the assumption, not the
behaviour.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
SCRIPT = ACP / "scripts" / "gen_progress_log.py"

RULE_FILE = "api/remediate_pdf.py"
TRAILER = "\n\nWCAG: 1.1.1 (pdf)\nMatrix-Note: none — test fixture.\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()


def _commit(repo: Path, path: str, text: str, message: str) -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _commit(r, RULE_FILE, "original\n", "chore: base")
    return r


def _check(repo: Path, since: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--check", "--since", since],
                          cwd=repo, capture_output=True, text=True)


def _merge_pr_style(repo: Path, branch: str) -> None:
    """What GitHub builds for a PR: base + branch merged, no fast-forward."""
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", f"Merge {branch} into main", branch)


def test_a_merge_is_skipped_even_when_both_sides_touched_the_same_rule_file(repo):
    """THE regression: the combined diff is non-empty, and the merge must still be skipped."""
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, RULE_FILE, "original\nfeature change\n", "fix(pdf): a change" + TRAILER)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, RULE_FILE, "base change\noriginal\n", "fix(pdf): base moved" + TRAILER)
    main_tip = _git(repo, "rev-parse", "HEAD")
    _merge_pr_style(repo, "feature")

    # Precondition: git really does list the shared file for this merge — without it the test
    # would pass for the wrong reason, exactly as the old implementation did.
    combined = _git(repo, "show", "--name-only", "--format=", "HEAD")
    assert RULE_FILE in combined, "the merge no longer produces a combined diff; fixture is stale"

    r = _check(repo, main_tip)
    assert r.returncode == 0, (
        "the guard flagged a merge commit, which can never carry a trailer:\n" + r.stderr)
    assert base                                    # (kept for readability of the range above)


def test_an_authored_commit_without_a_trailer_still_fails(repo):
    """The guard must keep doing its job — skipping merges is not skipping everything."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "changed\n", "fix(pdf): no trailer here")
    r = _check(repo, base)
    assert r.returncode == 1
    assert "has no Matrix-Note" in r.stderr


def test_an_authored_commit_with_a_trailer_passes(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "changed\n", "fix(pdf): declared" + TRAILER)
    assert _check(repo, base).returncode == 0


def test_a_non_rule_commit_needs_no_trailer(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "README.md", "docs\n", "docs: unrelated")
    assert _check(repo, base).returncode == 0


def test_a_malformed_trailer_is_caught_on_a_commit_that_touches_no_rule_code(repo):
    """The rule paths decide ONE question — whether a note is REQUIRED. They must not also gate
    whether a note that IS there gets parsed.

    A note on a docs commit went unvalidated: it passed review, and generation then skipped it
    for good, the message being unfixable by then. That is exactly how b13c700 ("docs: never push
    from the shared checkout") reached main carrying a note the generator could not read.
    """
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "README.md", "docs\n",
            "docs: something\n\nMatrix-Note: A real note with prose and no WCAG line at all.")

    r = _check(repo, base)
    assert r.returncode == 1, "a malformed trailer slipped through review on a non-rule commit"
    assert "no WCAG" in r.stderr


def test_a_non_rule_commit_with_a_WELL_FORMED_trailer_still_passes(repo):
    """The complement — validating more must not start demanding more."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "README.md", "docs\n",
            "docs: something\n\nWCAG: 1.1.1 (pdf)\nMatrix-Note: A real, valid note.")
    assert _check(repo, base).returncode == 0


def test_an_untrailered_commit_behind_a_merge_is_still_caught(repo):
    """Skipping the merge must not amnesty the commits it brought in — otherwise every
    undeclared change could be laundered through a PR."""
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, RULE_FILE, "original\nsneaky\n", "fix(pdf): undeclared change")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, RULE_FILE, "moved\noriginal\n", "fix(pdf): base moved" + TRAILER)
    main_tip = _git(repo, "rev-parse", "HEAD")
    _merge_pr_style(repo, "feature")

    r = _check(repo, main_tip)
    assert r.returncode == 1, "the undeclared commit was laundered through the merge"
    assert "undeclared change" in r.stderr
