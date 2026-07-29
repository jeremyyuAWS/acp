# CLAUDE.md

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
