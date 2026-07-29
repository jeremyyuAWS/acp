# CLAUDE.md

## Check for competing work before your first edit

Before editing a file, look at what is already in flight on it:

```
git fetch -q origin && git log --oneline origin/main -15
gh pr list --state open --json number,title,files -q '.[]|"#\(.number) \(.title)\n  \(.files[].path)"'
```

**If an open PR or a recent commit already touches the file you are about to edit, say so and
stop.** Tell the user what you found and let them decide. Do not open a competing PR.

**Why.** Sessions here do not see each other's work, and the same bug attracts several at once.
On 2026-07-29 `scripts/gen_progress_log.py` drew **seven PRs in one day** — #38, #44, #47, #48,
#49, #55, #56 — of which #49 and #55 were closed as redundant and #56 is still open behind
them. Separately #34 reimplemented the fix #30 had already merged, and was closed as a
duplicate. Not all seven overlapped, and none of the work was wrong. But some of it was done
twice, reviewed twice, and thrown away.

This costs more than the wasted effort: two sessions fixing one file produce conflicting
branches, and whichever merges second gets a rebase it did not need to earn.

## Isolate fix and feature work in a worktree

**Before the first edit** of a bug fix or a feature, call `EnterWorktree`. Before, not after —
once you have edits in the shared tree the move gets expensive (see below).

Exempt: read-only work — answering a question, reading code, reviewing a diff, running tests
you don't intend to change anything from. Isolation costs more than it saves there.

**Why.** This repo is routinely worked by many concurrent sessions. On 2026-07-28 seven of them
shared this one checkout — one index, one HEAD, one working tree between them — and it cost real
work:

- `api/remediate_pdf.py` was reset to HEAD mid-task and four applied edits vanished.
- The checkout was switched to another branch seconds after a push, so the next commit would
  have landed somewhere nobody intended.
- One session's uncommitted changes were swept into another session's commit.

None of that surfaces as an error. Edit tools still report success, tests then run against
reverted code, and the result reads as a bug in what you just wrote rather than a missing file.
The cost of not isolating is measured in re-derived work, not in warnings.

**If you are already in the shared checkout with uncommitted work**, do it in this order:

1. Commit your own paths first — `git add <specific paths>`. Never `git add -A` or
   `git commit -a`: the tree holds other sessions' half-finished work, and committing it for
   them has already happened.
2. Then call `EnterWorktree`. It branches from `origin/main` and switches your cwd, so
   uncommitted changes do **not** follow you — they stay behind, commingled with everyone else's.

**To check where you actually are**, at any point:

```
git rev-parse --show-toplevel   # must end in .claude/worktrees/<name>, not .../projects/acp
```

Worth running before a commit and before a push. Tool output does not say which checkout a
command ran in, and `cd`-ing to the shared checkout for a quick `git log` leaves you there.

**While in the shared checkout**, run `git branch --show-current` immediately before any commit.
It changes without warning; on 2026-07-28 it moved to a feature branch and back inside two
minutes. And if a git command fails on `index.lock`, another session is mid-commit — wait and
retry rather than deleting the lock.

## Never push from the shared checkout

Push only a branch you own, from your own worktree, and only when the user asks for it.

**Why.** `git push` sends every commit on the branch, not just yours. On a shared `main` that
means you publish whatever the other sessions have committed and not yet reviewed. On
2026-07-29 a single push from this checkout put **four commits from at least three different
sessions** onto `origin/main` at once — including one whose author had not been asked to push
anything, and the commit that added this very file. Nothing warned anybody; the session that
ran it was almost certainly pushing what it thought was its own one commit.

The commit-hygiene rule above (`git add <specific paths>`, never `git add -A`) does not protect
you here. That rule scopes what enters *your* commit. `push` operates on the branch, so it
carries everyone's commits regardless of how carefully each was staged.

**What to do instead.** From your worktree, push your own branch and open a PR:

```
git push -u origin <your-worktree-branch>
```

That is this repo's normal flow, not a ceremony added for the concurrency problem — 20 of the
last 30 commits on `main` arrived as numbered PR merges. The ten exceptions are all from
2026-07-28 onward and are the parallel-session work; direct-to-main is the anomaly here.

**If you find your work already on `main` because another session pushed it:** leave it. It is
published — rewriting shared history to undo it costs more than it recovers, and a force-push on
a branch four sessions are working from is far worse than an unreviewed commit. Tell the user it
happened and let them decide.

## Never merge red, and never merge on `mergeable` alone

Before merging, read the checks themselves:

```
gh pr checks <N> --json name,state -q '.[]|"\(.name): \(.state)"'
```

**Why.** `mergeable`/`mergeStateStatus` answer "would git combine these branches", not "is this
PR good". On 2026-07-29 they read `UNKNOWN` on several PRs — including #24 and #50 — purely
because GitHub had not finished computing them, seconds after CI had gone green. Waiting on that
field, or trusting it in either direction, tells you nothing about the tests.

Two states that are not failure, and must not be treated as one:

- **`cancelled`** means a newer push superseded the run, which is routine on `main` because the
  workflow sets `cancel-in-progress: true`. Three merges today showed `cancelled` on their own
  commit while the next commit's run passed. Confirm with
  `git merge-base --is-ancestor <your-sha> <green-sha>` before concluding anything.
- **A skipped test is not a passing test.** Engine-backed suites self-skip where the .NET CLI is
  not built, so a green local run can be silent about exactly the code you changed. On
  2026-07-29 a change went to CI with 1596 local passes and failed three engine-only tests that
  had skipped on the dev machine. When your change touches detector output, either build the
  engine or write the test so it needs no engine.

## Reproduce before you diagnose

An error message tells you a check failed. It does not tell you why, and its explanation of why
is frequently wrong. Build the failing case locally, watch it fail, apply the fix, watch it
pass — then ship that reproduction as a test with the fix.

**Why.** On 2026-07-29 the progress-log guard reported a commit as "has no `Matrix-Note:`
trailer". A session read that at face value and repeated it in a commit message, a PR, and a
message to another session. The trailer was there; the parser's SC pattern anchored on
end-of-line after the optional `(formats)`, so `WCAG: 1.1.1 (pdf), 4.1.2 (pdf)` matched nothing
and the commit read as untrailered. The session that wrote a fixture instead found it in
minutes (#47).

The same guard produced a second false story the same day: it flagged GitHub's own PR merge ref
for a missing trailer. The message was accurate and the conclusion it invited — "add a trailer"
— was impossible, because a merge commit has no authored message. Rebuilding that exact merge
locally showed `git show --name-only` emitting a *combined* diff, which is only empty when the
two sides touched disjoint files (#38).

**Corollary — check your own trailers against the parser, not against the docs.** Four merged
commits carried trailers the generator rejected, in four different ways, and log generation was
broken on `main` for a day before anyone noticed (#47). Two of them were written by a session
that had read the format and believed it was complying.

## Retire your worktree and branch after the PR merges

```
git worktree remove .claude/worktrees/<name> && git branch -d <branch>
```

Do it once the PR is merged and the remote branch is deleted, from the shared checkout (a
worktree cannot remove itself).

**Why.** On 2026-07-29 this repo held **15 worktrees** against one checkout, none retired, most
on branches already merged. They are not free: `git worktree list` stops being readable, several
were left `locked`, and a stale worktree sitting on a long-merged branch is an invitation for
the next session to start work from a base that is dozens of commits behind — which is how a
rebase-on-push becomes routine.

If the branch will not delete because it is not merged (`git branch -d` refuses), that is
information — check whether the work actually landed before forcing it.
