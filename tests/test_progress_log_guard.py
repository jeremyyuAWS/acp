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

import json
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


# ── a malformed trailer: fatal while it can still be amended, a warning once published ──
#
# It used to be fatal at BOTH moments, which put the only enforcement where nobody could obey
# it. `Matrix-Note:` with no `WCAG:` failed every push to main from 2026-07-29 — three commits
# on main carried it — and the notify workflow died in its first step, so the dispatch it
# guards never ran at all. Correcting a published message means rewriting shared history, which
# this repo forbids, so the failure had no exit.

MALFORMED = "\n\nMatrix-Note: A note with no WCAG trailer at all.\n"


def _generate(repo: Path, since: str | None = None) -> subprocess.CompletedProcess:
    args = [sys.executable, str(SCRIPT)] + (["--since", since] if since else [])
    return subprocess.run(args, cwd=repo, capture_output=True, text=True)


def test_check_fails_a_malformed_trailer_while_it_can_still_be_amended(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "changed\n", "fix(pdf): opted in badly" + MALFORMED)

    r = _check(repo, base)
    assert r.returncode == 1, "a trailer that cannot parse must fail at PR time"
    assert "no WCAG: trailer" in r.stderr
    assert "Amend the trailer now" in r.stderr


def test_check_catches_a_malformed_trailer_on_a_non_rule_commit_too(repo):
    """The note breaks its own entry whatever the commit touched."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "README.md", "docs\n", "docs: opted in badly" + MALFORMED)
    assert _check(repo, base).returncode == 1


def test_generation_warns_and_skips_instead_of_failing(repo):
    """The published-message case: never fatal, never silent."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "changed\n", "fix(pdf): opted in badly" + MALFORMED)

    r = _generate(repo, base)
    assert r.returncode == 0, "a published bad trailer must not fail the push"
    assert "::warning::" in r.stderr and "no WCAG: trailer" in r.stderr
    assert json.loads(r.stdout) == []


def test_one_bad_trailer_does_not_drop_the_good_entries_beside_it(repo):
    """The costly part of the old behaviour: the batch died with the offender, so well-formed
    entries in the same push never reached the matrix either."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "a\n", "fix(pdf): opted in badly" + MALFORMED)
    _commit(repo, RULE_FILE, "b\n",
            "fix(pdf): declared properly\n\nWCAG: 1.1.1 (pdf)\nMatrix-Note: A real entry.\n")

    r = _generate(repo, base)
    assert r.returncode == 0
    entries = json.loads(r.stdout)
    assert [e["title"] for e in entries] == ["fix(pdf): declared properly"]
    assert "::warning::" in r.stderr


def test_none_with_a_reason_is_the_omission_it_plainly_is(repo):
    """The root cause of the six bad commits on main: the docstring invites `Matrix-Note: none`,
    people write `none — why`, and an EXACT match read that as a real entry which then failed for
    the WCAG: trailer it never needed. Both spellings observed in the wild are covered."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "d\n",
            "fix(pdf): a\n\nMatrix-Note: none — no capability lane changes.\n")
    _commit(repo, RULE_FILE, "e\n",
            "docs: b\n\nMatrix-Note: none\nDocs only; no rule code touched.\n")

    r = _generate(repo, base)
    assert r.returncode == 0
    assert json.loads(r.stdout) == [], "a deliberate omission must produce no entry"
    assert "::warning::" not in r.stderr, "and no warning — nothing is wrong with these"
    assert _check(repo, base).returncode == 0, "nor may PR CI block them"


def test_a_note_opening_with_none_but_declaring_an_SC_is_still_an_entry(repo):
    """The loose match must not swallow a real note. It only applies where no SC was declared,
    so a genuine entry that opens with the word "None" is untouched."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "f\n",
            "fix(pdf): c\n\nWCAG: 1.1.1 (pdf)\nMatrix-Note: None of the detectors moved, but "
            "the applier now writes /Alt.\n")

    entries = json.loads(_generate(repo, base).stdout)
    assert len(entries) == 1 and entries[0]["scs"] == ["1.1.1"]
    assert entries[0]["summary"].startswith("None of the detectors")


def test_a_well_formed_commit_is_unaffected(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RULE_FILE, "c\n",
            "fix(pdf): declared\n\nWCAG: 2.4.6 (pdf, docx)\nMatrix-Note: Lead sentence here.\n")

    r = _generate(repo, base)
    assert r.returncode == 0 and "::warning::" not in r.stderr
    e = json.loads(r.stdout)[0]
    assert e["scs"] == ["2.4.6"] and e["formats"] == ["docx", "pdf"]
    assert e["summary"] == "Lead sentence here."


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
