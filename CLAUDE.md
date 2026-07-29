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

## Check whether someone is already fixing it

**Before the first edit**, look for work already in flight on the files you are about to touch:

```
git fetch -q origin && git log --oneline origin/main -15
gh pr list --state open --json number,title,files -q '.[]|"#\(.number) \(.title)\n  \(.files[].path)"'
```

If an open PR or a recent commit already touches your file, say so and stop. Comment on that PR
instead of opening a competing one.

**Why.** On 2026-07-29 a single parser bug in `scripts/gen_progress_log.py` was diagnosed and
fixed independently by at least four branches — `claude/fix-progress-log-generator`,
`fix/matrix-note-none-with-reason`, `worktree-progress-log-warn` and `fix-notify-none-parse` —
all committed within minutes of each other, and another session counted five sessions hitting
the same wall. Two of the resulting PRs then blocked each other as CONFLICTING, and one had to
be closed. Nobody was working from bad information; nobody could see anybody else.

The cost is not just duplicated effort. The PR that merged (#47) had the right diagnosis; two
others had a plausible-but-partial one, and a reviewer comparing them spent longer than writing
the fix would have taken.

## Reproduce before you diagnose, and ship the fixture

An error message is a claim, not evidence. Build the smallest input that triggers the behaviour
and run it before you write down a cause — and commit that fixture with the fix.

**Why.** `gen_progress_log.py` reported `has a Matrix-Note: but no WCAG: trailer` on two
commits. Both commits *had* the trailer:

```
676f081:  WCAG: 1.1.1 (pdf), 4.1.2 (pdf)
51a673b:  WCAG: 1.3.1 (html), 2.4.6 (html)
```

`_WCAG_RE` anchored `$` after a single criterion, so a comma-separated list matched nothing and
the code reported the trailer as missing. The message blamed the author for a parser bug. That
wrong cause was then repeated in a commit message, a PR body and a cross-session message before
anyone checked it — three artifacts, all confidently wrong, none of them cheap to retract.

The session that got it right wrote a fixture for the trailer format first and found the comma
case immediately. The session that got it wrong shipped no tests, which is exactly why it never
saw it. A fix without a fixture is a hypothesis that happens to have been committed.

The same rule applies to the capability grid: a cell moves on an observed detector run, never on
a plausible reading of a diff. On 2026-07-29 nine cells were corrected because the code was
checked against built fixtures, and one of them (`1.4.3` on PDF) turned out to be *shipping
damage* — its fixer rewrote compliant dark-theme PDFs into AA failures. No amount of reading
would have surfaced that; a fixture surfaced it in one run.

## Merging: green, verified, and actually resolved

- **Never merge red.** Check the suites explicitly, not the summary:
  `gh pr checks <N> --json name,state -q '.[]|"\(.name): \(.state)"'`
- **Do not trust `mergeable`.** GitHub reported `UNKNOWN` for a PR that merged perfectly
  cleanly; it computes lazily and is often stale right after a related merge. When it matters,
  trial-merge the real head:
  `git fetch origin refs/pull/<N>/head:pr<N> && git merge --no-commit pr<N>`
- **After resolving a conflict, verify before continuing.** `git add` followed by
  `git rebase --continue` will happily commit a file that still contains `<<<<<<<` markers —
  this happened on 2026-07-29 and was caught only because `node --check` runs over the page.
  Grep for markers before you stage.

**Holding a red PR is usually right.** Two PRs were held back on 2026-07-29 because they failed
a coverage-contract fixture whose expected counts they had changed but not updated. The fix for
that fixture landed on its own within the hour, both PRs went green, and their own sessions
merged them. Merging them red would have put `main` red for everyone and every later PR would
have inherited the failure.

## Retire the worktree when the PR merges

```
git worktree remove .claude/worktrees/<name> && git branch -d <branch>
```

**Why.** On 2026-07-29 this repo had 17 worktrees open at once, none of them retired after
their work merged. (They came down to 15 within the hour once sessions started cleaning up, so
this is a habit worth keeping rather than a one-off tidy.) Beyond the clutter, a merged branch
still held by a worktree cannot be deleted —
`gh pr merge --delete-branch` fails with *cannot delete branch used by worktree* — so the
branch list grows monotonically and stops being a usable index of what is actually in flight.

Name the worktree after the work, not the generator: `worktree-pdf-244-explain-only` can be
triaged from the list, `claude/unruffled-golick-29268b` has to be opened to find out what it is.
