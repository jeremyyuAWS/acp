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

## Don't read the shared checkout — it is stale, and it answers anyway

Its local `main` is only as current as the last session that pulled it, which may be never. It
does not error when it is behind; it just hands you last week's file. Ask the remote instead:

```
git -C <repo> show origin/main:<path>          # the file as it actually is
git -C <repo> grep -l "<symbol>" origin/main -- 'frontend/src/*.js*'
```

**Why.** On 2026-07-30 a session checked whether `noDraftHint` was still referenced before
deleting it, grepped the shared checkout, and found it live in `Remediate.jsx` — imported, called,
line and all. The checkout was four behind, and the code it printed had been deleted by a PR that
same session had written and merged. Later that day it found the checkout nine behind, then six.
The reading was confident, specific, and wrong in the one direction that matters: it says *keep
this* about something already gone.

Nothing about a stale checkout looks stale. `git status` is clean, the file opens, the symbol is
there. This is the "is this still used?" question specifically — the one whose wrong answer is
invisible, because deleting something still in use fails loudly and keeping something dead does
not.

**The preview server has the same root, and this one cannot be worked around.** `preview_start`
runs vite with the SHARED CHECKOUT as its root, whatever worktree you are in — so a browser check
of worktree changes exercises code that does not contain them, and passes.

Established by experiment on 2026-07-30, from a worktree, with a dev server running: a module
created only in the worktree was NOT served (vite answered `200` with the SPA fallback HTML, not
the file), while one created only in the shared checkout WAS served, with its contents. Do not
read this off the `/@fs` 403 instead — its allow-list names your worktree *and* the shared
checkout, so it looks like the worktree is in play when the root is not.

So: verify worktree changes at the DOM level in vitest, not in the browser pane, and say which you
did. A screenshot from that server is evidence about `main`, not about your branch.

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

The cheapest way to announce is to push. **Push your branch as soon as you have one commit**,
mid-task, long before the work is finished:

```
git push -u origin <your-worktree-branch>
```

An unpushed branch is invisible to every check above, including other sessions' re-checks. On
2026-07-29 `39f3c06` fixed the decorative-card defect completely — backend and card — then sat
unpushed, on no remote, with no PR. #43 independently rewrote the backend; #54 independently
rewrote the same three frontend files. By the time it was pushed it was redundant, and it never
merged. Every session involved had checked. There was nothing to find.

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

**A bite check that does not bite is a finding about your CLAIM, not a test that passed.** Break
the thing your fixture depends on and watch the suite go red; if it stays green, the dependency
you documented is not real.

**Why.** On 2026-08-30 the .pdf ground-truth corpus shipped with a comment saying 1.4.3 needs an
explicit background rect, because pptx's contrast detector abstains on a shape with no fill and
the same trap was assumed to transfer. Deleting the rect left all 34 tests passing.
`_pdf_char_background` falls through to `_PDF_DEFAULT_BG` ("FFFFFF"), so a bare page IS measured,
against white — PDF's real abstentions are a glyph over an image and one straddling a fill's edge.
The comment was confident, plausible, reasoned by analogy from a real trap in another format, and
wrong. Nothing but the failed bite check would have caught it.

Two more of that day's claims died the same way. `2.4.2` and `3.1.1` on pdf were recorded as
unreachable — "tag-tree semantics or langdetect" — and each is one `pikepdf` dictionary lookup in
a tree vendored since ADR 0029; the source was a stale header in `tests/engines.py` saying the PDF
engine "lives outside this repo entirely", false for months and contradicted by its own code
twelve lines below. And "build the Office analyser in CI" was written into a gap analysis as the
top recommendation when `ci.yml:125` and `azure-pipelines.yml:86` have both been building it all
along. Three claims, one root cause: a comment was read where a command should have been run.

**A pipeline hides whether the command ran at all**, and reports the failure as a pass. Read the
exit status of the command itself, not of a pipeline, and address the repo explicitly:

```
git -C <repo> remote prune origin -n > /tmp/out 2>&1; echo "exit=$?"; cat /tmp/out
```

Two shapes to distrust. `cmd | grep X || echo "clean"` prints `clean` when `cmd` fails outright —
`grep` cannot distinguish "no matches" from "nothing ran". And `cmd | tail; echo "exit=$?"` reports
`tail`'s status, which is `0` no matter how `cmd` died.

**Pass `git -C <repo>` rather than trusting the shell's cwd**, which does not survive
`git worktree remove`: the shell is left in a deleted directory and silently resolves to the
non-repo parent, where every git command fails identically.

**Why.** On 2026-07-29 one session hit both halves within the hour. It ran
`gen_progress_log.py --check | tail -4; echo "exit=$?"`, read `exit=0`, and reported the matrix
guard as passing — that `0` was `tail`'s. Then, having just removed its own worktree, it ran
`git remote prune origin -n | grep 'would prune' || echo "none"` from the cwd that removal had
invalidated: every git call died with `fatal: not a git repository`, `grep` matched nothing, and
the command printed `none`. That was reported as a clean prune. Nothing had run, and the only
reason it surfaced was an unrelated `fatal:` leaking into the next command's output.

Both commands were written *to verify* — which is what makes the shape worth knowing. A check
that cannot fail is indistinguishable from a check that passed.

### `pytest tests/` is NOT the backend CI job

The "Backend suite" job runs **four** checks, and the test suite is only the first. Running
pytest and calling the job verified is a claim about three checks you did not run:

```
python -m pytest tests/ -q            # the suite
python scripts/gen_matrix_coverage.py --check    # capability ceiling still derivable
python scripts/gen_todo_status.py --check        # docs/TODO.md coverage block is current
python scripts/gen_progress_log.py --check       # rule changes declare their matrix impact
```

The last one is the one that bites, because **nothing local prompts you for it**. It fails when a
commit touches `RULE_PATHS` — which includes the bare prefix `api/remediate`, so
`remediate_office.py` and `remediate_pdf.py` both match — without a `Matrix-Note:` trailer in its
message. The fix is a trailer, or `Matrix-Note: none` to record that the omission was considered.

**Why.** On 2026-08-06 #141 (`44d04d0`) changed both remediate files, was verified with the full
suite green (2112 passed) and merged during a GitHub Actions outage that stopped CI running at
all. When Actions recovered, the suite passed on ubuntu and this guard failed: the squash commit
carried no trailer. By then the message was published and could not be fixed, so that change has
no `PROGRESS_LOG` entry and never will — the guard exists precisely to stop that, and it was
bypassed by verifying the wrong thing rather than by anything the guard got wrong.

Two things worth knowing about the failure mode:

- **It is transient on `main`, permanent in the record.** `--check` scans `HEAD~1..HEAD` (or the
  PR's own commits when `BASE_REF` is set), so the next commit to land clears the red. What does
  not come back is the declaration the commit should have carried.
- **The trailer is a per-commit fact.** A follow-up commit cannot supply one for its predecessor,
  and rewriting published history to add it is worse than the omission (see "Never push from the
  shared checkout"). Get it right before the squash, or accept the gap and say so.

So: run all four before pushing anything under `RULE_PATHS`, and when you tell someone you ran
"the workflow's own commands", make sure that is the whole job and not the part you happened to
think of.

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

## PR workflow — open ready-for-review and enable auto-merge immediately

CCR (cloud remote) sessions cannot call the `/merge` REST endpoint on protected branches — the
proxy blocks it. The workaround is **auto-merge**: GitHub fires the squash itself once all required
checks pass.

**The rule:** every PR must be opened **ready-for-review** (not draft) so auto-merge can be
enabled, and auto-merge must be enabled immediately after `gh pr create` (or the equivalent API
call). Do not create draft PRs on this repo.

**Arm it by adding the `automerge` LABEL**, which is this repo's own gate:

```python
import urllib.request, os, json
token = os.environ.get('GITHUB_TOKEN', '')
headers = {'Authorization': f'token {token}',
           'Accept': 'application/vnd.github.v3+json',
           'Content-Type': 'application/json',
           'User-Agent': 'python-urllib'}
req = urllib.request.Request(
    f'https://api.github.com/repos/jeremyyuAWS/acp/issues/{pr_number}/labels',
    data=json.dumps({'labels': ['automerge']}).encode(),
    headers=headers, method='POST')
with urllib.request.urlopen(req) as r:
    print('labels now:', [l['name'] for l in json.load(r)])
```

`.github/workflows/auto-merge.yml` fires on `labeled` and runs `gh pr merge --auto --squash` under
a GitHub App token. Read its policy before assuming a label is enough: **`hold-for-review` beats
`automerge`**, a draft is skipped, and — the part worth knowing — a PR that is armed *without* the
label gets its auto-merge **actively disabled** on the next event. So the label is not one of
several ways to arm it; it is the authorisation, and arming around it is a change the workflow may
undo.

**`PUT /pulls/{n}/automerge` DOES NOT EXIST. This file recommended it, and it cannot work.**
Measured 2026-09-01 with `GITHUB_TOKEN`: that call answers `404 Not Found` while
`GET /user` returns `jeremyyuAWS` and `GET /pulls/1155` returns `200` on the same token in the same
second — so it is the endpoint, not the scope. GitHub's auto-merge has no REST endpoint at all; it
is the GraphQL mutation `enablePullRequestAutoMerge`, **and GraphQL is blocked in a CCR session**:

    403 This GraphQL query is not enabled for this session — only the pinned set of
        PR-review operations is served.

Both halves of the documented workaround were therefore dead, which is why the label is the recipe.
The `mcp__github__enable_pr_auto_merge` tool does work, but it arms the PR directly and so bypasses
the policy gate above, and it spends the shared account rate limit (see the budget section) — on
2026-09-01 it returned `API rate limit already exceeded for user ID 102616407` mid-session while
`GITHUB_TOKEN` still had its full 15,000. Prefer the label; keep the tool for when the label is not
appropriate, and say which you used.

**Auto-merge means minutes, so a follow-up commit needs its OWN PR from the start.** Once
auto-merge is armed, the squash lands as soon as the required checks pass — routinely inside
five minutes on this repo. A second commit pushed to that branch after the merge goes nowhere: the
branch still exists, the push succeeds, and the work is simply not on `main`.

**Why.** On 2026-08-30 this happened three times in one session — #1012, #1014 and #1018 — each
time to a commit held back for a local full-suite run that took longer than the merge did. #1018
is the instructive one: its squash on `main` is titled "8 pairs, 32 -> 40 (65%)", the first commit
only, while the branch carried a second commit correcting a factual error in the first. Nothing
warned. The PR read as merged, the branch read as pushed, and the correction was on neither.

Two habits follow. **Push and let CI verify** rather than holding a commit for a local suite —
the local run is not the CI job anyway (see above), and holding costs the merge window. And when
a PR you own has merged, **check by CONTENT that what you think landed actually did**:

```
git fetch -q origin main && git show origin/main:<path> | grep -n "<the line you changed>"
```

A squash title names the first commit, not the branch. Reading the title is how a missing
correction stays missing.

## Don't exhaust the shared GitHub API budget — stop polling

The authenticated GitHub API limit is **5,000 requests/hour PER ACCOUNT, not per session** — every
concurrent Claude session on this machine draws from the SAME 5,000. The fastest way to burn it is a
CI-watch loop, and a loop that is harmless solo is not harmless ×5.

**Why.** On 2026-08-21 this account's GraphQL budget hit zero inside the hour and stayed there,
blocking `gh pr create` for 15+ minutes at a stretch — several times in one session. Nothing was
wrong with the PRs; the cause was **polling**. Each "watch CI until green" loop calls `gh pr checks`
/ `gh run view` every 20–30s — dozens of calls per PR over a few minutes — and there were several PRs
in flight across ~5 concurrent sessions sharing one budget. The work itself (a handful of PRs) would
never have come close; the *watching* did.

**What actually counts, and what is free.** `git push` is the git protocol, not the REST/GraphQL
API — it does **not** count, so push freely. The `/rate_limit` endpoint is **exempt** — checking the
budget is free (`gh api rate_limit --jq '.resources.graphql.remaining'`). Conditional requests that
come back `304 Not Modified` don't count either. What DOES count is every `gh pr` / `gh run` / `gh
api` read — those are the polling calls that drained it.

**What to do.**

- **Don't poll CI in a tight loop.** If you must poll, use **≥60s** intervals, run **one** watcher at
  a time, and stop the instant the run completes. Prefer a single check after a sensible wait over a
  fast loop.
- **Let GitHub do the waiting instead of you.** `gh pr merge --auto --squash` merges the PR the
  moment its required checks pass — no polling from you at all — and `deploy.yml`'s `workflow_run`
  trigger then deploys on merge. This is the frugal default for "merge on green"; it needs branch
  protection on `main` with the CI checks marked required (a repo-settings decision — ask the user
  before changing merge policy for everyone).
- **Assume the budget is already half-spent by other sessions.** Check `…graphql.remaining` before a
  burst of PR work; if it's low, do the essential calls and let the rest wait for the top-of-hour
  reset rather than hammering (hammering also trips the separate *secondary* limit).
- **Move waiting into Actions where you can.** Anything polled *inside* a workflow spends the repo's
  `GITHUB_TOKEN` budget (1,000/hr **per repo**), which is separate from the user's 5,000/hr.

**Raising the ceiling is an org action, not a code change** — note it to the user, don't try to code
around it: a **GitHub App** installation token has a separate, larger budget that scales with the
install (≈12,500/hr for orgs); **GitHub Enterprise Cloud** raises the user limit to 15,000/hr. Until
one of those exists, the answer to a hit limit is *stop polling and wait for reset*, never *retry
harder*.

## Retire your worktree after the merge

```
git log origin/main --format='%h %s' | grep -F "(#<PR>)"   # confirm the squash actually landed
git worktree remove .claude/worktrees/<name> && git branch -D <branch>
```

**`-D`, not `-d`.** This repo squash-merges, so your commit never becomes an ancestor of `main`
and `git branch -d` refuses to delete a branch whose work is fully merged. On 2026-07-29 neither
`7c978f2` (merged as #43) nor `39f3c06` was an ancestor of `main`, so neither appeared in
`git branch --merged`. `-d` buys you no safety here, only a refusal that looks like a warning —
so confirm the squash by its PR number first, and then `-D` is a considered act rather than the
thing you reach for when `-d` fails.

**But `-d` has a SECOND failure mode, and it is not the squash.** `git branch -d X` deletes only
if X is merged into its upstream — or into **HEAD** when it has no upstream. In the shared
checkout HEAD is your local `main`, which goes stale the moment you stop pulling it. So `-d` also
refuses branches that merged perfectly normally, no squash involved: on 2026-07-29
`git branch -d worktree-matrix-sync` refused while `git merge-base --is-ancestor
worktree-matrix-sync origin/main` returned true — the commits were literally in `origin/main`,
and local `main` was seven behind.

That matters because the advice above ("`-d` buys you no safety here") is true of a
squash-landed branch and false in general. On a stale HEAD the refusal is real information, and
`-D` at that moment discards work nobody has merged. Fetch first, so a refusal means something:

```
git fetch -q origin && git checkout main && git merge --ff-only origin/main
```

Grep the subject, not the message: `git log --grep` searches the body too, and later commits
routinely cite earlier PR numbers. Confirming #43 that way returns #51, whose body mentions it.

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
- **"The worktree is gone" does not mean the branch is free.** A worktree can be recycled to a
  NEW path on the same branch, and git refuses to delete a branch any worktree still holds:

  ```
  error: cannot delete branch 'X' used by worktree at '/…/<name>'
  ```

  On 2026-07-29 a session was told its worktree had been retired and the branch was safe to
  delete; it had in fact been recycled to a new directory, still on that branch. Check
  `git worktree list` for the branch, then `git checkout --detach origin/main` there before
  deleting. This bites hardest when the two steps are done by different sessions, which is the
  order this section describes.

## Keep retired features in the tree — but write down that they are retired

When a feature is removed from the UI, **delete the mount, not the code**. The owner's standing
instruction (2026-08-21): leave features we no longer use in the codebase so they can be brought
back if needed. Restoring a panel should be one commit.

So: take out the `<Component />` and its import, leave `Component.jsx` and its tests where they are.

**But an orphan you do not write down becomes a lie.** On 2026-08-20 ten components sat on `main`
that nothing rendered — `AssessSetup`, `AssessFileFindings`, `DeliveryPanel` and the rest, each
merged with passing tests and a green suite. Every one read as shipped on every status list. Two
were reported to the owner as "wired" before anybody checked. The failure is invisible by
construction: these components return `null` when they cannot derive anything, so *never mounted*
and *mounted with the wrong props* both render blank and the suite stays green either way.

Both halves are needed, and they are not in tension:

- **Keep the file** so the decision is reversible.
- **Assert the orphan in a test** so it cannot be mistaken for live code — see
  `discoverUploadRemoved.test.jsx` (Upload) and `scopeStep.test.js` (ScanScope). Each names the
  component, asserts nothing mounts it, and says the removal was deliberate. When it is mounted
  again, that test fails, which is the reminder to delete the test rather than a regression.

The other direction has its own guard: `lastTwoWiring.test.jsx` sweeps every component written for
the approved design boards and fails if any is not rendered by some screen. Retired features are
not on that list; components that are supposed to be live are.

**Currently retired or unmounted, and mounted nowhere** (frontend/src): `AssessScope`,
`AssessmentReconciliation`, `ConfidenceDashboard`, `ControlPlane`, `Dashboard`,
`DiscoverCompleteSummary`, `DiscoveryCompleteness`, `Disposition`, `DispositionReviewWorkspace`,
`EstateCoverage`, `EstateTreemap`, `FileTypeConfig`, `Insight`, `LiveAssessment`, `PiiPanel`,
`ProcessingDetails`, `RemediationApprovals`, `RiskScore`, `RolePrivilege`, `Rubric`, `ScanScope`,
`ScanScopeChip`, `ScanSetup`, `ScopeFunnel`, `ScopeRules`, `ScreenReaderDemo`, `Upload`,
`WordCloud`.

Do not delete these, and do not "wire them back in" because they look unfinished — several were
removed on purpose, and one (`RemediationFixPreview`, since deleted) shipped live in exactly that
way after a session read *unmounted* as *unfinished*. Check the git history and the issues before
assuming a gap.

**This list is enforced, not maintained by hand.** `unmountedComponents.test.jsx` derives the set
and asserts it matches this paragraph exactly, in both directions — a component that stops being
rendered fails until it is added here, and a listed one that gets mounted fails until it is removed.
Update the two together; they are the same fact.

**Why it is enforced now.** It was hand-maintained and it drifted. A 2026-08-30 audit found
**17** unmounted components against the **12** listed — and two of the five missing ones
(`ScopeFunnel`, `ProcessingDetails`) were additionally *imported* by `App.jsx` without ever being
rendered, so the tree read as wired to anyone who grepped. `ScopeFunnel` was worse: `live_snapshot.py`
cited it twice as the authority for the eligible-count figure — a backend docstring grounding a
number's honesty in a surface no user has ever seen. Both imports and both citations are now gone.

Four of these (`Dashboard`, `ProcessingDetails`, `ScanSetup`, `ScopeFunnel`) were **never mounted at
any point in this repo's history** — verified with `git log -S`. They are unbuilt, not retired, which
is a different thing and worth knowing before treating one as a feature someone removed.

Note what is deliberately NOT on the list: `Transparency.jsx` and `charts.jsx` have no default export
and exist only for their named ones (`TraceChip`, `RuleBreakdown`, `Donut`, `Bars`), which are
imported and used throughout. A module with no component to mount is not an orphan; an earlier pass
of the audit flagged both, and that was the false positive.
