# CLAUDE.md

## Isolate fix and feature work in a worktree

**Before the first edit** of a bug fix or a feature, call `EnterWorktree`. Before, not after —
once you have edits in the shared tree the move gets expensive (see below).

Exempt: read-only work — answering a question, reading code, reviewing a diff, running tests
you don't intend to change anything from. Isolation costs more than it saves there.

Confirm where you actually are before editing — the answer must be a worktree, not the shared
checkout, and it is easy to believe you moved when you did not:

```
git rev-parse --show-toplevel    # .../.claude/worktrees/<name>, NOT .../projects/acp
```

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

## Claim the files before you start

Before your first edit, look for someone already doing the work:

```
git fetch -q origin && git log --oneline origin/main -15
gh pr list --state open --json number,title,files -q '.[]|"#\(.number) \(.title)\n  \(.files[].path)"'
```

**If an open PR or a recent commit already touches the file you are about to edit, say so and
stop.** Do not open a competing PR. Tell the user what you found and let them decide whether to
join that work, wait for it, or proceed anyway.

**Why.** Isolation stops sessions from corrupting each other's *files*; it does nothing to stop
them doing the same *task*. On 2026-07-29 several sessions independently found and fixed the
same defect, and the duplication only surfaced at merge time — by which point every one of them
had written tests, a commit message, and a PR body for it. Worktrees make this failure quieter,
not rarer: nobody sees a conflict, everybody sees a clean branch.

Thirty seconds of looking is cheaper than a second correct fix nobody needed.

**Checking once is not enough, and this is the part that actually bit.** On 2026-07-29 a session
checked `main` before every piece of work it started and was still duplicated three times — by
#30, #38 and #47. Every collision landed *after* its check and *before* its push, in the minutes
CI takes to run. A check at the start proves nothing about the state at the end.

So re-check immediately before you push, and treat what you find as a real answer rather than a
formality:

```
git fetch -q origin main && git log --oneline <your-branch-point>..origin/main -- <files you touched>
```

When it comes back non-empty, read the commit before you push. Twice that day the honest outcome
was to drop most of a branch and keep only the part the other fix had missed — which is a better
result than merging a second implementation of the same thing, and it is only available if you
look before the merge rather than after.

Better still where you can: say what you are about to work on *before* you start. Checking makes
*you* discover a collision; announcing prevents one for everybody else. Nothing in the check-first
rule stops two sessions that both looked, both saw nothing, and both began.

## Verify before you diagnose

Reproduce a failure yourself before you believe what it says, and ship a test with the fix.

**Why.** Error messages describe a symptom, not a cause, and a plausible reading of one
propagates fast. On 2026-07-29 a session read "no `WCAG:` trailer" from an error, repeated that
diagnosis in a commit message, a PR body, and a message to another session — and the trailer was
there all along, comma-separated, with the parser at fault (fixed in #47/#48). The session that
took the time to build a fixture found the truth in minutes.

The same day, a session reported **32 pre-existing test failures across 8 modules** and carried
that claim through four PRs. Every one was a missing dependency in its own venv — the suite is
green on a complete install. Nothing in the repo was broken; the environment was, and "the tests
were already failing" is a claim that stops anybody from looking.

If you are about to describe something as pre-existing, broken, or unrelated, that is exactly
the claim to check first — it is the one that ends the investigation.

**Ship the fixture, not just the fix.** A fix without one is a hypothesis that happens to have
been committed — and the fixture is what finds the case you did not think of. On 2026-07-29 the
capability grid's cells were re-checked by running the real detectors against built files rather
than by reading them: nine cells turned out to be understated, and `1.4.3` on PDF turned out to
be *shipping damage* — its fixer assumed a white page and rewrote compliant dark-theme PDFs from
21:1 down to 3.66:1, an AA failure it created, unattended. No amount of reading the diff would
have surfaced that. One fixture surfaced it on the first run.

## Never merge red, and don't trust `mergeable` alone

Read the checks themselves:

```
gh pr checks <N> --json name,state -q '.[]|"\(.name): \(.state)"'
```

**Why.** `mergeable` is computed asynchronously and reports `UNKNOWN` while GitHub is still
thinking — on 2026-07-29 it did so for PRs that were perfectly mergeable, and a session only
established that by trial-merging. `UNKNOWN` means *ask again*, never *blocked* and never *safe*.

It reads as "probably fine" and it is not. The same day, the same `UNKNOWN` on #48 turned out to
be a genuine conflict: `gh pr view 48` reported `UNKNOWN`, the merge was attempted on the strength
of that, and GitHub refused it —

```
GraphQL: Pull Request has merge conflicts (mergePullRequest)
```

— because #47 had landed in the gap. Both directions came from the same value on the same day, so
do not learn "`UNKNOWN` is usually mergeable" from the first story. Resolve it before you act,
either by re-reading it or by letting the merge attempt itself be the test; a refused merge is
free, and merging on the assumption is not.

Two more things that day's merges cost:

- **A squash merge deletes the base branch, and that auto-closes anything stacked on it.** #36
  was closed two seconds after its base merged, and GitHub will not reopen a PR whose base is
  gone — it had to be reopened as a new PR. Retarget dependents to `main` *before* merging their
  base.
- **A local suite passing is not CI passing.** Wait for the real run.
- **`git add` + `git rebase --continue` will commit a file that still contains `<<<<<<<`.**
  Git treats staging as "resolved" and asks no further questions. On 2026-07-29 a conflict
  resolution silently failed — the script meant to perform it errored — and the markers were
  committed and pushed; only `node --check` running over the page caught it. Grep for markers
  before you stage, not after.

## Retire your worktree after the merge

```
git worktree remove .claude/worktrees/<name> && git branch -d <branch>
```

**Why.** On 2026-07-29 this repo held 16 worktrees and none had been retired. Each one is a full
checkout that goes stale the moment `main` moves, and a stale worktree is where the next session
runs tests against code that was replaced a day ago.

Later that day one session retired its four, and the count is now in single figures — so this is
a habit that works, not a lost cause. Two things make it safe to do:

- **A squash merge gives your commit a NEW sha, so your branch will never be an ancestor of
  `main`.** `git log origin/main..<branch>` therefore lists your commit forever and looks like
  unmerged work. Compare CONTENT instead, scoped to the files you changed —
  `git diff origin/main <branch> -- <paths>` empty means it landed. Read that way, a branch that
  appeared to hold 968 unmerged lines turned out to be merged and simply behind.
- **Do not remove the worktree you are standing in.** Leave it first (`ExitWorktree`, or `cd` to
  the main checkout); `git worktree remove` on your own cwd leaves the shell in a deleted
  directory. Removing another session's worktree is worse — check `git worktree list` and retire
  only your own.
