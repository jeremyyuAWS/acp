"""The Matrix-Note CI guard: it must judge authored commits, and only authored commits.

scripts/gen_progress_log.py --check fails a commit that touches rule code without declaring its
matrix impact. CI runs it as `--check --since origin/$BASE_REF`, and on a pull request the
checkout is GitHub's test-merge ref — so the range contains a MERGE commit nobody wrote.

The regression pinned here: the guard used to skip merges implicitly, relying on
`git show --name-only` printing nothing for them. That is only true when the two sides touched
DISJOINT files. `git show` renders a merge as a COMBINED diff, listing whatever differs from
every parent, so a PR whose base had also edited one of its rule files produced a non-empty list
— and CI demanded a `Matrix-Note:` trailer from GitHub's own merge commit. There is no message
to put one in, so the PR could not go green by any action its author could take. Observed on
PR #39, whose base had edited api/proposals.py in #25 while the branch edited it too.

The fix (#38) skips by PARENT COUNT instead. These tests exist because that fix shipped
untested, and the failure it prevents is invisible until it happens to someone: the guard stays
green on every ordinary commit whether or not the skip is correct.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "scripts"))

import gen_progress_log as guard  # noqa: E402

RULE_FILE = "api/proposals.py"          # in guard.RULE_PATHS
PLAIN_FILE = "docs/notes.md"            # not rule code


def _run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _commit(repo: Path, path: str, text: str, message: str):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    _run("git", "add", path, cwd=repo)
    _run("git", "commit", "-m", message, cwd=repo)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A throwaway repo with one commit on `main`. guard._git shells out in the process cwd."""
    r = tmp_path / "repo"
    r.mkdir()
    _run("git", "init", "-q", "-b", "main", cwd=r)
    _run("git", "config", "user.email", "t@example.com", cwd=r)
    _run("git", "config", "user.name", "T", cwd=r)
    _commit(r, PLAIN_FILE, "base\n", "chore: base")
    monkeypatch.chdir(r)
    return r


def _base(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


# ── the guard still guards ─────────────────────────────────────────────────────

def test_rule_code_without_a_trailer_fails(repo):
    """If this ever passes, every test below is vacuous — the guard would be a no-op."""
    base = _base(repo)
    _commit(repo, RULE_FILE, "x = 1\n", "fix(x): touch a rule file")
    assert guard.check(base) == 1


def test_rule_code_with_matrix_note_none_passes(repo):
    base = _base(repo)
    _commit(repo, RULE_FILE, "x = 1\n",
            "fix(x): touch a rule file\n\nMatrix-Note: none — no capability change.")
    assert guard.check(base) == 0


def test_a_commit_touching_no_rule_code_needs_no_trailer(repo):
    base = _base(repo)
    _commit(repo, PLAIN_FILE, "more\n", "docs: not rule code")
    assert guard.check(base) == 0


# ── THE regression: GitHub's test-merge ref ────────────────────────────────────

def _pr_shaped_merge(repo: Path) -> tuple[str, str]:
    """Reproduce PR #39's exact shape and return (base_before_merge, merge_sha).

    A branch and its base BOTH edit the same rule file, in DISJOINT hunks, then the base merges
    the branch — which is what GitHub builds to test a PR whose branch has fallen behind.

    The disjointness is the whole point. git auto-merges both edits, so the merged file carries
    the branch's change AND the base's, and therefore matches NEITHER parent — which is exactly
    when a combined diff lists it. Resolve in favour of one side instead (`-X theirs`) and the
    result equals that parent, the combined diff comes back empty, and the scenario silently
    stops reproducing the bug. In #39 the two hunks were #25's chart helper and this branch's
    `proposal()` signature, far apart in api/proposals.py.
    """
    top, bottom = "# region A\ntop = 0\n", "# region B\nbottom = 0\n"
    _commit(repo, RULE_FILE, top + ("filler\n" * 20) + bottom,
            "chore: seed the rule file\n\nMatrix-Note: none — setup.")

    _run("git", "checkout", "-q", "-b", "feature", cwd=repo)
    _commit(repo, RULE_FILE, top.replace("top = 0", "top = 1") + ("filler\n" * 20) + bottom,
            "fix(feature): edit the top of the rule file\n\nMatrix-Note: none — declared.")

    _run("git", "checkout", "-q", "main", cwd=repo)
    _commit(repo, RULE_FILE, top + ("filler\n" * 20) + bottom.replace("bottom = 0", "bottom = 1"),
            "fix(base): edit the bottom of the same rule file\n\nMatrix-Note: none — declared.")

    before_merge = _base(repo)
    _run("git", "merge", "-q", "--no-ff", "feature", "-m", "Merge feature into main", cwd=repo)
    return before_merge, _base(repo)


def test_the_merge_commit_really_does_list_rule_files(repo):
    """Guards the guard's test. If the combined diff were empty here, the merge would be skipped
    for the wrong reason and test_a_pr_shaped_merge_is_skipped would prove nothing."""
    _, merge_sha = _pr_shaped_merge(repo)
    listed = subprocess.run(["git", "show", "--name-only", "--format=", merge_sha],
                            cwd=repo, check=True, capture_output=True, text=True).stdout.split()
    assert RULE_FILE in listed, (
        "the merge no longer produces a non-empty combined diff — this scenario stopped "
        "reproducing the CI failure it was written for")


def test_a_pr_shaped_merge_is_skipped(repo):
    """THE regression. The merge carries no authored message, so it cannot declare anything; the
    changes it brings were each judged on their own trailer already."""
    _, merge_sha = _pr_shaped_merge(repo)
    parents = subprocess.run(["git", "log", "-1", "--format=%P", merge_sha], cwd=repo,
                             check=True, capture_output=True, text=True).stdout.split()
    assert len(parents) == 2, "fixture stopped producing a real merge"

    # Range spanning the whole thing — base commit, both sides, and the merge.
    root = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=repo,
                          check=True, capture_output=True, text=True).stdout.split()[0]
    assert guard.check(root) == 0, (
        "the guard flagged GitHub's merge commit for a Matrix-Note it cannot carry — a PR in "
        "this shape cannot be made green by its author")


def test_a_merge_does_not_launder_an_undeclared_commit(repo):
    """Skipping merges must not become a way to smuggle rule changes past the guard: the branch
    commit is still judged on its own trailer, merge or no merge."""
    root_before = _base(repo)
    _run("git", "checkout", "-q", "-b", "sneaky", cwd=repo)
    _commit(repo, RULE_FILE, "undeclared = 1\n", "fix(x): rule change with NO trailer")
    _run("git", "checkout", "-q", "main", cwd=repo)
    _run("git", "merge", "-q", "--no-ff", "sneaky", "-m", "Merge sneaky into main", cwd=repo)

    assert guard.check(root_before) == 1, (
        "an undeclared rule change reached main behind a merge commit")
