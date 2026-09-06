# ADR 0051 — `Last-Event-ID` resume for the remediation stream

**Status:** Accepted — implemented; both Open items closed by ADR 0052
**Date:** 2026-09-05
**Related:** ADR 0042 (durable scan lifecycle event log) — this is the PR 5 that ADR deferred to
"its own ADR after PRs 1–4 have run in production". Code: `api/routes/scans.py`
(`stream_remediation_status`, `scan_events` read route), `api/store.py` (`list_scan_events`,
`append_scan_event`), `frontend/src/api.js` (`parseSSEFrames`, `openRemediationStream`).
PRD: `docs/prd-remediation-realtime-ops-panel.md` §8 (event stream), §17.6 (reconnect with a
missed event), §22 (event retention).

---

## Context

ADR 0042 built the log and said why it stopped short of resuming on it:

> **PR 5 (deferred, not proposed here) — `Last-Event-ID` resume on a stream.** SSE's native resume
> header, replaying `scan_events` from the client's last `seq`. Genuinely valuable and genuinely
> the riskiest thing in this space: it changes the reconnect *contract*, not just a frame.

Everything that resume needs is already here. `scan_events.seq` is per-scan monotonic behind a
UNIQUE index, assigned inside the INSERT so two racing writers cannot share a position (measured:
12/12 gap-free against a naive design's 2/12). `list_scan_events(after_seq=...)` is the replay
read, and `GET /scans/{sid}/events?after_seq=` already serves it. Remediation began writing eight
`remediate.*` kinds into that same log in #1391.

What does not exist is any client that resumes. `GET /scans/{sid}/remediation/stream` re-pushes a
whole snapshot whenever one changes and emits no event identity at all; on reconnect the client
starts from nothing and simply renders whatever the next snapshot says. Nothing is lost from the
DATABASE — the log is durable — but the narrative is: every event that occurred while the
connection was down is invisible to that browser forever.

### The constraint that decides the design

**SSE's native resume is not available to ACP, and the ADR that deferred this assumed it was.**

The browser sends `Last-Event-ID` automatically only for `EventSource`. ACP does not use
`EventSource` anywhere and cannot: every authenticated call carries a bearer token in a header,
`EventSource` cannot set headers at all, and the alternative — the token as a query parameter —
would put it in proxy access logs and browser history, which this codebase avoids deliberately
(`api.js` says so at the Discover stream, in a HIPAA/BAA context). So every ACP stream is
`fetch()` + a `ReadableStream` reader with a hand-written frame parser.

Two consequences, and they are the whole of this ADR:

1. **The client must carry the cursor itself.** There is no browser machinery to inherit.
2. **`parseSSEFrames` discards `id:` lines today.** It reads `event:` and `data:` and nothing else,
   so even if the server emitted ids, no client could see one.

## Decision

### 1. The cursor travels as a request header, named `Last-Event-ID`

Keeping the SSE name even though nothing about it is automatic: it is the same concept, a reader
who knows SSE reads it correctly, and inventing `X-Acp-Event-Cursor` would buy nothing.

A **header**, not a query parameter, for the reason the bearer token is a header — request URLs
reach proxy access logs and browser history, and a per-scan event cursor is not secret but the URL
it would sit next to is already carrying a scan id we prefer not to spread.

### 2. The stream emits two frame types, and the existing one is unchanged

| Frame | `event:` | `id:` | Payload |
|---|---|---|---|
| Snapshot (existing) | *(default `message`)* | none | the current `remediation_status` + `snapshot`, exactly as today |
| Event (new) | `remediation-event` | the event's `seq` | one `scan_events` row, plus the run `revision` it produced |

The snapshot frame is untouched, deliberately. It is what the shipped progress bar and
`RemediationOpsPanel` consume; a client that ignores the new frame type behaves exactly as it does
now. That is what makes this rollout-safe: the contract change is additive on the wire, and the
reconnect contract only changes for a client that opts in by sending a cursor.

### 3. Replay happens once, at connect, before any live frame

Given `Last-Event-ID: N`, the stream first yields every event with `seq > N`, oldest first, each
with its own `id:`. Then it enters the existing snapshot loop. A client therefore sees the history
it missed in order, and only then the present.

### 4. Three conditions force reconciliation instead of replay

The server emits `event: reconciliation-required` and no replay when it cannot honestly serve the
cursor:

- **`N` is ahead of the log** (`N > max(seq)`). The cursor is from another scan, or from a run
  whose rows were removed. Replaying "everything after N" would yield nothing and look identical
  to "you are caught up", which is the dangerous reading — the client would believe it had missed
  nothing.
- **The log has been pruned past `N`** (`min(seq) > N + 1`). The events between are gone.
- **`N` is unparseable.** A malformed cursor is a client bug; reconciling is the safe response.

On that frame the client fetches a fresh snapshot and resets its cursor to the newest `seq`, per
PRD §17.6 — "a reconnect with a missed event fetches a fresh snapshot before rendering later
events".

### 5. Retention is DECIDED but NOT IMPLEMENTED, and the gap check is written for its absence

> **Superseded 2026-09-05 by ADR 0052, which added the pruning.** The reasoning below is kept
> because it is the argument for writing an unreachable branch, and that argument was paid off:
> when `store.prune_scan_events` landed, the pruned-past-`N` condition worked on the first run and
> its fixture could prune for real rather than construct the state by hand.

PRD §22 settles retention at 24 hours or 10,000 events per run, whichever is greater. **Nothing
prunes `scan_events` today.** The pruned-past-`N` condition above is therefore unreachable in
production right now, and this ADR does not add pruning: retention is a separate change with its
own risks (a delete that races an append, a run whose history vanishes mid-read), and shipping the
resume contract does not depend on it.

Writing the check now anyway is deliberate and cheap. It costs one `MIN(seq)` in a query that
already runs, and it means the day pruning arrives, resume does not silently start losing events
in exactly the window where nobody is looking.

## Consequences

**A reconnecting panel keeps its narrative.** Region E's activity feed, when it is built, can show
what happened while the tab was backgrounded rather than starting blank.

**The riskiest part is bounded by the opt-in.** ADR 0042 called this "the riskiest thing in this
space" because it changes the reconnect contract. It changes it only for a client that sends a
cursor; every other consumer, including the shipped progress bar, sees the same stream it sees
today.

**Replay is bounded.** `list_scan_events` takes a `limit` (default 500). A client resuming from a
very old cursor gets the first 500 missed events and a cursor to continue from; it does not get a
single frame containing an entire run's history.

**One more thing the panel can be wrong about, and is not.** A resumed client could render events
whose `revision` predates the snapshot it already has. `remediationSnapshot.isNewer` already drops
a snapshot whose revision went backwards; event frames carry the revision so the same rule extends
to them.

## Alternatives considered

**Switch to `EventSource` and get resume for free.** Rejected: it cannot carry the bearer token,
and moving the token to the URL trades a logging/privacy property this codebase has deliberately
maintained for a mechanism we can implement in twenty lines.

**Replay from a timestamp instead of a seq.** Rejected for the reason ADR 0042 already documented
when choosing `seq`: events for one scan can be written from more than one replica, `occurred_at`
is a wall clock, and a cursor over `(occurred_at, event_id)` silently skips a late-arriving event
stamped before the cursor. A resume that loses events is worse than no resume.

**Send the whole history on every connect and let the client de-duplicate.** Rejected: it makes
every reconnect O(run length), and the client cannot de-duplicate what it never saw — it would have
to keep every event id it has ever rendered.

## Open

**Both were closed by ADR 0052.** Kept here rather than deleted, because what each one turned out
to cost is the useful part:

- ~~**Pruning**, per §22's 24h/10,000 decision. The gap check lands here; the deletion does not.~~
  Landed in `store.prune_scan_events`, run hourly by the sweeper. The `events_pruned` reconcile
  branch below is now reachable, and its fixture prunes for real instead of issuing a DELETE that
  imitates one — which is the whole reason the branch was written before anything could produce
  the condition.
- ~~**Whether the stream should stay open past `in_flight == 0`.**~~ It does now, while the
  snapshot's own `completing` state ("delivery_reconciliation_outstanding") holds. The caution
  above was right about the risk and wrong about the shape: `_stream_is_finished` keeps the
  `in_flight` gate as its first clause, so the change can only ever extend the stream, never
  shorten it — which is what makes it safe for `onDone`/`finishRemediation`. It deliberately does
  NOT stay open for `needs_attention`; a review decision may be hours away, and the client already
  polls there.

Still open:

- **Per-phase stall thresholds** (PRD §18). ADR 0052 added §22's lease clause to the stall
  predicate, which needed no per-format evidence; the thresholds themselves still do.
