# ADR 0043 — SSE resume for scan progress: `Last-Event-ID` rejected, history-on-reconnect adopted

**Status:** Proposed — **design only, no code**
**Date:** 2026-08-29
**Related:** ADR 0042 (the durable scan-lifecycle event log, all four PRs shipped 2026-08-29), which
deferred this decision to its own ADR. Code: `api/routes/scans.py` (the three SSE endpoints,
`GET /scans/{sid}/history`), `frontend/src/api.js` (`parseSSEFrames`, `openDiscoverStream`),
`frontend/src/App.jsx` (`pollScanJob`), `frontend/src/liveJobStateGuard.js`,
`frontend/src/useLiveSnapshot.js`.

---

## Context

ADR 0042 named a fifth PR and deliberately did not design it:

> **PR 5 (deferred, not proposed here) — `Last-Event-ID` resume on a stream.** SSE's native resume
> header, replaying `scan_events` from the client's last `seq`. Genuinely valuable and genuinely
> the riskiest thing in this space: it changes the reconnect *contract*, not just a frame. It
> should be its own ADR after PRs 1–4 have run in production, and it is the reason `seq` is
> designed as a resume cursor now even though nothing resumes on it yet.

This is that ADR. The design work turned up five facts about the code as it actually stands, and
together they change the answer.

### What was verified, not assumed

Every claim below was checked against `origin/main` at `5a7f0a39`.

**1. Nothing emits `id:` today.** No `yield "id: …"` exists in any of the three SSE generators. The
server-side half of `Last-Event-ID` is entirely unbuilt.

**2. The client's SSE parser silently discards `id:`.** `api.js`'s `parseSSEFrames` recognises
exactly two line types:

```js
if (line.startsWith('event:')) event = line.slice(6).trim()
else if (line.startsWith('data:')) data = line.slice(5).trim()
```

An `id:` line matches neither and is dropped. Its own comment says comments and ids "are not"
recognised because "the backend emits neither" — accurate, and it means the client half is unbuilt
too.

**3. The discover stream is not a browser `EventSource` at all.** `openDiscoverStream` reads it with
`fetch` + a `ReadableStream` reader, deliberately: `EventSource` cannot send custom headers, and
putting a bearer token in the URL would place it in proxy access logs and browser history — which
this app avoids everywhere, being HIPAA/BAA-scoped. **The browser's `Last-Event-ID` machinery
therefore does not apply to this stream at all.** Resume here would be entirely hand-rolled:
tracking the last id, reconnecting on our own timer, and sending the header ourselves.

**4. The one native `EventSource` closes on error, so auto-reconnect never fires.** `App.jsx`'s
`pollScanJob` is the app's only `new EventSource(...)`, and its error handler is:

```js
es.addEventListener('error', (e) => {
  if (settled) return
  settled = true
  es.close()
  …
  else { _pollScanJobPolling(job_id).then(resolve, reject) }
})
```

It settles and closes on the first error, then degrades to polling. The browser never gets to
auto-reconnect, so it never gets to send `Last-Event-ID`. Making that header useful means **first
changing this reconnect path to stop closing** — which is precisely the code ADR 0042 kept PR 4
away from, and the code behind the 2026-08-26 reconnect-freshness incident.

**5. `GET /scans/{sid}/events` has no consumer.** The Assess running screen mounts
`LiveAssessmentLive`, which uses `useLiveSnapshot` — a `setInterval` **poll** of
`GET /scans/{sid}/live` every 2000 ms. Nothing in `frontend/src` opens `/scans/{sid}/events`.

> **This corrects ADR 0042.** Its endpoint table listed that stream's client as
> "native SSE auto-reconnect (`liveAssessment.js`)". `liveAssessment.js` is a *normalizer* imported
> by the polling hook, not a stream consumer. The endpoint is an orphan — built to the Live
> Assessment PRD §8 and never wired. Building resume for it would be building for nobody. See
> "Consequences" for what to do about the orphan itself.

### The finding that actually decides it

**These streams are snapshot-replace, not event logs.** `liveJobStateGuard.js` states it directly:

> The stream is a snapshot-REPLACE, not an event log — each `data:` frame is the job's full current
> state, not a delta.

`Last-Event-ID` exists to solve a specific problem: *a consumer of a delta stream missed deltas
N+1…M and cannot reconstruct state without them.* That problem does not exist here. Every frame is
the complete current state, so the first frame after any reconnect already **is** the answer.
Replaying frames 40–57 to a client that is about to receive frame 58 delivers seventeen superseded
copies of a value it is one tick from having.

So the honest statement of what a disconnect costs is not *state* — it is **narrative**. A `phase:
"retrying"` that came and went while the tab was asleep is invisible afterwards, because the
snapshot moved on. That is a real loss, and it is worth fixing.

It is also **already fixed**. ADR 0042 PR 3 shipped `GET /scans/{sid}/history?after_seq=N`, which
returns exactly the events a client missed, from a durable table, ordered and gap-free. The cursor
`seq` was designed for this — ADR 0042 said so at the time.

---

## Decision

**Reject `Last-Event-ID` resume. Adopt history-on-reconnect instead:** when a stream ends or
reconnects, the client issues one `GET /scans/{sid}/history?after_seq=<highest seq held>` and
renders what it missed.

Concretely, the difference:

| | `Last-Event-ID` resume | History-on-reconnect (adopted) |
|---|---|---|
| Server change | `id:` on every frame in 3 generators; a replay path keyed on the header; new per-connection state | **none** — the endpoint shipped in PR 3 |
| Client change | track ids, hand-roll reconnect for the fetch-based stream, stop `pollScanJob` closing on error, teach `parseSSEFrames` about `id:` | one `GET` in the existing `onDone` handler |
| Touches the reconnect contract | **yes** — the settle/close semantics behind two of the four 2026-08 fixes | **no** |
| Delivers the narrative | yes | yes |
| Delivers state faster | no (the next snapshot arrives anyway) | no (same) |

The adopted option delivers the entire user-facing benefit at a fraction of the risk, because the
work was already done by PRs 1–4. That is the whole argument.

### Why not build it anyway, for correctness' sake

Two reasons, and neither is "it is hard".

**It would encode a promise the transport cannot keep.** An `id:` on a snapshot frame implies that
replaying from it reconstructs something. It does not — snapshots are not composable. A future
reader would reasonably assume the stream is resumable in the event-sourcing sense and build on
that assumption. Emitting a header whose semantics we do not honour is worse than not emitting it.

**The `seq` namespace collision is a live hazard.** Two different counters are already in play:
Redis's per-job `HINCRBY seq` (what the stream frames carry, what `liveJobStateGuard` compares) and
`scan_events.seq` (per-scan, gap-free, what `/history` uses). They are not comparable, and a
resumable stream would have to put one of them in `id:`. Whichever we picked, the other would be a
foot-gun sitting one field away — and `liveJobStateGuard` silently *drops* frames on a bad seq
comparison, so the failure would be an invisible missing update rather than an error.

---

## What "history-on-reconnect" means in practice

Not proposed for implementation in this ADR — recorded so the follow-up is small and unambiguous
when someone wants it.

**Where.** `openDiscoverStream`'s `onDone` (which fires for both `event: done` and `event: error` —
the 2026-08-26 rule, unchanged) and the `error` branch of `pollScanJob`. Both already have a
natural "the stream ended" moment; this adds a read there and nothing else.

**What it does NOT change**, and these are the invariants any implementation must re-assert:

- `event: done` and `event: error` both still mean "the stream ended". A history fetch is not a
  reason to reinterpret either.
- `pollScanJob` still settles once and still degrades to `_pollScanJobPolling` on a transport
  error. The history read is additive; it is not a new retry path.
- `liveJobStateGuard.acceptLiveJobState` still governs the live job-state ref. **History rows must
  not be fed into it** — they are a different shape with a different `seq` namespace (see the
  hazard above). They belong in the narrative surface (`ScanHistory`), not the progress card.
- The 4-missed-poll fallback frame and its `live: false` marking (ADR 0042 PR 4) are untouched.

**Ordering note.** `after_seq` is exclusive and `scan_events.seq` is gap-free per scan, so "highest
seq held, exclusive" is exact — no windowing, no dedupe, no clock involved. That is the property
`seq` was given in ADR 0042 precisely so this call could be trivial.

---

## When this decision should be revisited

Named so a future reader can tell whether the reasoning still holds rather than re-deriving it:

1. **If any stream becomes a delta stream.** The moment a frame stops being full current state, the
   argument above inverts and `Last-Event-ID` becomes the right mechanism.
2. **If a genuinely event-sourced stream is added** — e.g. a live tail of `scan_events` itself for
   an operator console. That stream *would* be resumable in the real sense, and it should carry
   `id: <scan_events.seq>` from its first commit rather than have it retrofitted.
3. **If per-file events are ever admitted to `scan_events`** (ADR 0042 excluded them, and its
   retention arithmetic depends on that). At thousands of rows per run, a reconnecting client
   fetching the whole missed range starts to look like a stream, and the trade shifts.
4. **If the discover stream ever moves to a native `EventSource`** — which would require solving
   the auth-header problem that drove it to `fetch` in the first place. Then the browser's resume
   machinery is free rather than hand-rolled, and only reasons (1) and the `seq` collision remain.

None of these hold today.

---

## Consequences

**Gained.** The narrative-across-a-disconnect gap is closable with one `GET` in an existing
handler, against an endpoint already shipped and tested. The reconnect contract — the code with
four fixes behind it in two weeks — is not touched. `scan_events.seq` keeps its single, unambiguous
meaning.

**Given up.** Nothing a user would notice. The theoretical loss is sub-second latency on the first
post-reconnect state, and it is theoretical because the next snapshot arrives on the stream's own
250 ms/1 s cadence regardless.

**RESOLVED 2026-08-30 — the orphan endpoint.** `GET /scans/{sid}/events` is
live, owner-scoped, tested (`tests/test_live_events.py`) and consumed by nothing. Per CLAUDE.md's
standing convention — *keep retired features in the tree, but write down that they are retired,
because an orphan you do not write down becomes a lie* — it should either be wired to the Assess
running screen (replacing the 2 s poll in `useLiveSnapshot`, which is the thing it was built for)
or explicitly recorded as unmounted, with a test asserting the absence the way
`discoverUploadRemoved.test.jsx` does for `Upload`. Right now it reads as shipped live-streaming on
any status list, and it streams to nobody. **That is a separate decision from this one** and is not
proposed here; it is named because this ADR's research is what surfaced it.

The owner delegated this call and it was made: **option (b), left unmounted with a guard test**
(`frontend/src/liveEventsStreamUnused.test.js`), because wiring it is not the clear improvement the
choice was conditioned on. The deciding fact is a cost inversion: the stream's generator calls
`build_snapshot` — real DB work — every `_STREAM_INTERVAL_S` (**1.0s**) per connected client against
the poll's **2.0s**, so it is *more* Postgres read load per viewer, plus a held socket and coroutine
each, in exchange for one second of latency. In a repo that throttled `_maybe_checkpoint` to one
write per 20s after the 2026-08-26 connection exhaustion, that is the wrong direction. Three further
costs stack on it: no browser `EventSource` can carry this app's bearer header (so a client means a
second hand-rolled `fetch`+`ReadableStream` reader), `_MAX_STREAM_ITERS` means a long run outlives
its own stream and needs reconnect logic the poll does not, and `useLiveSnapshot`'s three documented
guarantees — sequence guard, fail-soft, refocus-fresh — would each need rebuilding on the stream
path. This ADR's own finding is the fifth: a snapshot-REPLACE stream buys little over a poll.

The endpoint is kept, not deleted. If the interval is reconciled, the auth-header problem is solved,
or a genuinely event-sourced stream replaces the snapshot one, wiring becomes live again — and the
guard test failing is the reminder to delete the test, not a regression.

**Explicitly not decided here.** Whether the Assess running screen should stream rather than poll;
whether `scan_events` should ever carry per-file rows; and anything about the three streams'
existing terminal rules, which stand unchanged.
