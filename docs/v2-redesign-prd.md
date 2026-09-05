# PRD — ACP v2 redesign

**Status:** in progress · **Source:** the v2 requirements list, 2026-08-07 · **Fork:** was `frontend-v2/` (#139); the fork **replaced `frontend/` in place** on 2026-08-19 and no longer exists as a separate tree — paths below that say `frontend-v2/` mean `frontend/`.

This is written from the raw requirements list rather than around it, so each line is traceable
back to something that was actually asked for. Where an item is done it says which PR did it, and
where a requirement turned out to mean something different from its wording, that is recorded
rather than quietly reinterpreted.

---

## 1. Problem

The app is too busy. An operator opening ACP meets nine workflow tabs, eleven settings tabs, and
eight stacked panels on the remediation screen — most of which are reference rather than work.
The decision that matters most, *what should this engagement assess*, was reachable only through
an admin screen nobody opens, after discovery had already run.

Two consequences drive everything below:

- **The critical choice happened too late.** Narrowing scope after a scan leaves the results on
  screen disagreeing with the scope beside them.
- **The product could state a verdict and not explain it.** "1.3.1 fails" with no way to ask what
  ACP actually checked.

## 2. Goals

1. Choosing what to assess happens **before** discovery, in one control.
2. That choice **carries through** discovery → assess → remediate → publish without re-plumbing.
3. Every screen shows **less**, and what remains is what an operator acts on.
4. Any criterion can answer **"what do you actually check?"** in the words of the engineer who
   maintains the detector.

## 3. Non-goals

- Migrating to Postgres. It is already a supported backend (`DATABASE_URL`, psycopg2 pool).
- Cross-tenant administration. The store defends tenant isolation in at least four places
  deliberately; a superuser view is a security decision, not a UI one, and is out of scope here.
- Scoring model quality. The comparison harness prints drafts and refuses to score them.

---

## 4. Requirements, and where each one landed

### 4.1 Shipped

| # | Requirement (as written) | Outcome | PR |
|---|---|---|---|
| 1 | Ability to select which rules need to run | The `scan_scope` setting — a per-criterion, per-format map | #145, #153 |
| 2 | Need to filter by file types | **Same mechanism.** Not a second control | #145, #153 |
| 3 | Remove permissions | Settings tab and panel removed | #151 |
| 5 | Need architecture for each rule Assess/Remediation | Per-rule detail generated from `docs/rules/*.md` | #155 |
| 6 | Show 17 rules | Criterion table defaults to the tracked 17; the pre-discovery scope grid offers `SCOPE_UNIVERSE ∩ TRACKED_17`, so the other 12 — AAA rules and viewer behaviours — are not rows to dismiss on the first screen an operator sees | #155, #168 |
| 7 | App is too busy | Nav 9→8, Settings 11→8, −661 lines | #151 |
| 9 | Make remediation collapsible | Four reference sections collapse; the work inbox does not | #154 |
| 12 | Remove Upload | Tab removed, capability folded into Discover | #151 |
| 13 | Remove Validation coverage | Removed | #151 |
| 14 | Business ontology remove | Editor removed; the data path is untouched | #151 |
| 18f | Keep scoring rules & File types tab | Kept | — |
| 18g | For the 14, more detail on Assessment and Remediation | Answered by #155 — e.g. 1.3.1 on DOCX now states the `Heading 1..9` level-skip rule | #155 |
| 18h | Take What's Changed out of Overview | Removed | #151 |
| 18a | Control plane: filter by dept, user, Enterprise | `/control/estate` + a Settings tab. It filters, it does not merely display: department and owner are inputs, and the tenant comes from the request and is never a parameter | #159, #160, #165 |
| 15 | File types and custom file-type exclusions | `FileTypeConfig` now WRITES `scan_scope`, so the toggles gate assessment and remediation instead of only filtering the Discover list — which is what the panel had always claimed | #166 |
| — | Scope visibility in Remediate and Publish | `ScopeBanner` names both the criterion scope and the run boundary, above the counts it qualifies | #164 |
| — | SharePoint alongside Google Drive | Sites, libraries, a picker in Discover, and server-side write-back that replaces the original after archiving it | #156, #157, #158, #167, #171 |

**Three requirements were one mechanism.** "Select which rules", "filter by file types" and
"pick the SCs" are all `scan_scope`, which already existed and already gated the pipeline. The
work was making it reachable and correct, not building it — see §5.

### 4.2 In progress

| # | Requirement | State |
|---|---|---|
| 8 | Remediation more intuitive | Collapsing shipped (#154). The live running-stage experience is defined in §7.1; the focused review-queue redesign remains specified separately in `docs/remediate-redesign-spec.md` |
| 4 / 18c | List of users with access to ACP | **The tab is a mock.** `UserManagement.jsx` renders a hardcoded `SEED_USERS` array and imports nothing from `api.js`; there is no `/users` route on the backend. It looks authoritative and is not, which is worse than absent |

### 4.3 Already built — the requirement may have been about something narrower

| # | Requirement | What is actually there |
|---|---|---|
| 18e | Make Disposition policies work | **Built front and back, and this PRD was wrong to call it untouched.** `api/routes/disposition.py` + `api/disposition.py` (ADR 0003 Phase 3) with `tests/test_disposition_execute.py`; `Disposition.jsx` is 258 lines covering policy CRUD, preview, execute, the approval queue and the audit trail, reachable at Settings → Disposition. Policies are created disabled, approval-gated by default, and "delete" is always Drive trash. **What may have prompted the requirement:** in the SIM build every one of those clients returns synthetic data (`_simDisp`), so on a demo deployment the whole tab is theatre — which is exactly what "make it work" would describe |

### 4.4 Clarified rather than built

| # | Requirement | What it turned out to be |
|---|---|---|
| 18d | "Remediated storage - ollama" | Ollama is the **AI provider** (`api/ai.py`), not storage. It has always been the default. Now in the local compose stack with a model-comparison harness (#161) |
| 18b | Remove permissions tab | Duplicate of #3 |

---

## 5. The carry-through, and why it needed no re-plumbing

The scope gate lives in `_rule_outcome`, which is *"the one place a verdict is decided"*. It is
applied there before any lane branching, so:

| Stage | Inherits by |
|---|---|
| Assess | `in_scope()` inside `_rule_outcome` — an out-of-scope pair reads NOT_EVALUATED |
| Remediate | the deterministic fixers take the same `in_scope` predicate (`handlers.py:478`) |
| Publish | reads `get_certification_facts`, which is *"the SAME `_rule_outcome`"* |

`publish.py` never mentions scope, correctly — it cannot publish a verdict that was never
produced. **Gate once at the authoritative point; everything downstream inherits.**

---

## 6. Open work, in priority order

Everything the first version of this list held has since merged — scope visibility (#164), the
control plane surface (#165) and the two file-type controls (#166). What remains:

1. **Per-document filtering as a first-class carry-through.** `restrictedBySelection` narrows a run
   by marked document through a mechanism entirely separate from `scan_scope`. Every other filter —
   criteria, formats — funnels through the one gate in `_rule_outcome` and inherits assess,
   remediate and publish for free (§5). This one does not, so it is the single remaining gap in
   "the filter carries through everywhere".

   **Corrected 2026-08-21: this is not a Discover item.** The row said "Discover's
   `restrictedBySelection`" from the day it was written. It lives in `remediableScope.js` and is
   read by `Remediate.jsx`; `git grep restrictedBySelection` finds nothing in `Discover.jsx`. The
   gap is real, the tab named was not — which is the failure §"A note on reading this document"
   below was added to warn about, landing on the very list that warning sits under.
2. **Make the Users tab real, or stop shipping it.** A hardcoded roster that reads as live data
   is a worse answer than an empty state. Needs a backend; none exists.
3. **Decide what the SIM build should claim.** Disposition, Rubric and Test users all return
   synthetic data there. That is defensible for a demo and indefensible if anyone reads a demo as
   a capability statement — and requirement 18e suggests somebody already did.

### A note on reading this document

§4.3 exists because this PRD asserted, for two weeks, that Disposition policies were untouched
while a full implementation sat in `api/routes/disposition.py` with tests. Nobody checked,
because the document was the thing being checked against.

So: **verify against the tree before planning from any row here.** A status column is a claim
about the past, and this repo moves faster than the claim does.

---

## 7. Remediation experience

### 7.1 Live running stage

Remediation is the longest-running stage. While it is active, the page must continuously show
material progress without turning each event or refresh into motion. The operator should be able
to answer four questions at a glance: **Is the run alive? Where are the documents? How quickly are
they moving? What needs attention?**

#### Visual hierarchy

The running view is ordered by operational value:

1. Headline and connection freshness.
2. Reconciled segmented progress and changes since the previous visual update.
3. Active document pipeline.
4. Throughput bars and a calibrated ETA range.
5. Recent activity.
6. Exceptions and actions.

The following elements make up that view.

1. **Animated document pipeline.** Show document counts across
   `Waiting → Applying → Verifying → Saving → Delivered`. A document slides/fades only when its
   state changes; an SSE event or data refresh that leaves it in the same state causes no motion.

2. **Live deltas.** `Completed`, `Fixes applied`, `Verified`, and `Delivered` may show a short-lived
   positive delta (for example, `36  +3`) with a brief green highlight. Do not celebrate increases
   in waiting, failure, or retry counts, and do not animate a value whose previous state was
   unknown as though it increased from zero.

3. **One reconciled segmented progress bar.** Replace a single fill bar with mutually exclusive
   `Completed | Processing | Waiting | Review | Failed` partitions whose counts reconcile to the
   run total. Hover and keyboard focus expose the exact count for every segment. Color is never
   the only distinction: use visible labels and/or patterns as well.

4. **Moving throughput window.** Show documents completed per minute as bars over the most recent
   five minutes, with new bars entering from the right. Re-bin and redraw on a 10–15 second visual
   cadence rather than for every SSE event. Pair it with the existing calibrated ETA range.

5. **Concurrent phase activity.** Show `Prepare`, `Applying`, `Verifying`, `Saving`, and
   `Finalizing` independently. A soft pulse marks a phase with current work; more than one phase
   may be active because documents move through the pipeline in parallel. A completed phase uses
   a stable check and an inactive future phase uses a stable outline.

6. **Recently completed ticker.** Put the newest material event at the top, for example a file
   verified, delivered, or scheduled to retry. New rows slide in; older rows remain readable and
   age out without fading to low contrast. Relative times update without re-animating the row.

7. **Per-document progress trails.** Expand detailed milestones for at most the three visible
   active documents: `Opened → fixes applied → Verifying → Saving`. Other documents remain
   summarized in the stage counts so the page does not grow with the batch.

8. **Queue-flow animation.** A restrained moving dash may show real work flowing through
   `Queue → Workers → Verification → SharePoint`. Run it only while documents are advancing. Stop
   it when the run is waiting, disconnected, or stalled; do not animate every React Flow edge.

9. **Rate change.** Beside the current throughput, compare it with the preceding five-minute
   window (for example, `22.4 documents/min ↑ 18%`). Use a short transition for the arrow and value.
   Omit the percentage until both windows contain enough completed documents for a meaningful
   comparison.

10. **Completion milestones.** Use subtle, dismissible notices only at meaningful thresholds:
    the first corrected copy delivered, a configured document-count milestone, and halfway through
    the batch. Do not notify for every document, and never let a notice obscure an exception or
    action.

11. **Explicit connection state.** Text always communicates one of:
    `Live`, `Reconnecting · last update … ago`, `Updating by polling`, or
    `Stalled · no material progress for …`. The icon may animate, but is supplementary. Mark the
    run stalled after 15 minutes without material progress, not merely 15 minutes without an SSE
    heartbeat.

12. **Optional activity pulse.** A narrow strip may show event density over the last 60 seconds.
    Label it as activity, not completion, and keep it subordinate to reconciled progress. It can be
    hidden without losing any operational fact.

#### Motion and accessibility contract

- Animate real state changes only. Refreshes, heartbeat events, and relative-time updates do not
  replay entrance, delta, or milestone motion.
- Honor `prefers-reduced-motion`: update content immediately with no sliding, pulsing, moving
  dashes, or animated value interpolation.
- Never flash faster than three times per second. Motion does not move keyboard focus, alter
  reading order, or create routine live-region announcements.
- When the tab is hidden, continue ingesting and reconciling SSE data but pause visual motion.
  On return, render the latest state once; do not replay the accumulated transition history.
- **Pause visual updates** freezes animation and visual transitions only. It does not pause backend
  work, disconnect SSE, stop polling fallback, or prevent the data model from reaching the latest
  state. Resuming shows the reconciled current state rather than replaying queued animations.
- Failure, retry, disconnection, and stall states remain calm and explicit. They never borrow the
  green increase treatment or celebratory milestone motion.

#### Acceptance criteria

- At every snapshot, the five progress partitions are mutually exclusive and sum to the run total;
  no document is counted in two partitions or disappears between them.
- A document transition animates once per durable state change, even if the same event is received
  more than once or a poll repeats the current state.
- Throughput bars update no more frequently than once per 10 seconds and retain a five-minute
  window; insufficient data produces a plain calibrating state rather than a fabricated zero or
  percentage change.
- All segment counts, phase states, connection states, ticker entries, and controls are operable and
  understandable with a keyboard, a screen reader, color removed, and reduced motion enabled.
- Hidden-tab and paused-visual modes continue to ingest events and converge to the same reconciled
  state as the normal live view.
- A connection can be live while material progress is stalled. Heartbeat freshness and progress
  freshness are measured and communicated separately.

### 7.2 Open questions — blocked on a decision, not on effort

| Question | Why it needs an answer |
|---|---|
| "Fix Language -" | Truncated in the source notes. Cannot be scoped |
| "Need to flush out Publish so that the Remediation…" | Truncated |
| "Make this filter work:" | Truncated — appears to have had a screenshot attached |
| What does "more intuitive" mean beyond collapsing? | #154 shipped the collapsing. The rest is a design brief nobody has written |
| ~~Should either write-back button replace originals at all?~~ | **Answered: yes, replace, after archiving.** Both SPAs now write through `/sharepoint/upload` with `item_id`; the server archives to `_mova-originals/<date>/` and a failed archive aborts the write (#171, #172). Replacing keeps the item's URL, sharing links and version history, so people holding a link get the remediated file. **Drive is still the odd one out** — its archive is best-effort (`catch { }`), so a failed archive there is followed by the overwrite anyway. That is now the only inconsistency left, and it is the unsafe direction |
| Artifact-level provenance for SharePoint | Folder-scoped exclusion ships today and is the approach `provenance.py` rejects for Drive. The stronger version needs `Sites.Manage.All` |

---

## 8. Success criteria

- An operator can choose criteria and formats **before** the first scan, in one control, and see
  that choice reflected on every screen that reports against it.
- No screen shows a total whose denominator is not stated on the same screen.
- Any criterion in the table can answer "what do you check?" without leaving the page.
- Removing a surface never leaves prose pointing at it. *(#151 failed this — three dangling
  "Settings → …" references survived the deletion and were fixed in #154. It is a success
  criterion because it was missed once.)*

---

## 9. Numbers this product quotes, and which one is which

Recorded because the redesign added a fifth, and the defence against a sixth is that nothing may
retype one.

| Count | Name | Answers |
|---|---|---|
| ~38 | Traced | Did ACP look at this criterion on this format? |
| 29 | `SCOPE_UNIVERSE` | Which (criterion, format) pairs may an operator scope? |
| 20 | Document core | What does the product certify against? |
| **17** | **Tracked** (`MOVA_TRACKED`) | **What does this customer follow?** |
| 14 | Agreed scope (`engagement-14`) | What did we agree to assess for this engagement? |

17 = the document core minus 1.4.4, 1.4.10 and 1.4.12 — resize, reflow and text spacing, which
are viewer behaviours rather than properties of a static document. The relationship is pinned by
a test so a future reader does not "restore" them as an oversight.
