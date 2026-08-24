# ACP — gap closure backlog

Every item below is a gap **observed** on 2026-08-08, not a speculative improvement. Each names
the evidence, so anyone can re-check it rather than trust this file.

**Updated 2026-08-09 (late).** 21 PRs landed today — deploy went automatic (Chain B fires on CI
success), docx 1.1.1/2.4.4/3.1.2 consolidated onto the capability registry (ADR 0031), and Phase 5
under-reporting closed. The full list is in **Closed on 2026-08-09** near the foot of this file;
read the "Still open after today" note there before approving any deploy. Phase 5 itself: P5.1
(#214), P5.2 (#215) and P5.5 (#216) closed — each measured with a red fixture before any fix — and
P5.3/P5.4 marked blocked on installs (LibreOffice, a mutation runner) rather than on design.

**Synced 2026-08-09.** Six entries had gone stale in two days — Phase 0 was fully closed, P2.4,
P2.5 and P4.8 were done, and P4.2 was half done — while the file still listed all of them as open.
That is worth a warning rather than just a fix: **this file goes out of date faster than anything
else in the repo, and it is the one artifact people read INSTEAD of checking.** Where it and the
code disagree, the code wins; each item now names what to re-run. The measured claims here
(lane counts, undeclared pairs, per-SC bounds) came from
`remediation_capability.CAPABILITY`, `store.RULE_FORMATS` and `scripts/score_assessment.py` on the
day of the sync, not from the previous version of this file.

Context: the customer is a **hospital**, the documents are **PHI**, and the near-term scope is
**.docx only**. Those three facts set the priority order more than anything else here.

**Status key:** `[ ]` open · `[~]` in progress · `[x]` done · `[?]` needs a decision, not code

**Updated 2026-08-14 (pilot-readiness pass).** Ahead of a 3-user pilot, a fresh gap sweep — the new
items are in **Phase R** immediately below. Two are ops-blocking (a wedged deploy, an unwired GPU
vision lane); the rest are the four demo-pillar features and the verification holes, each named with
what to re-run. The capability-completion counts (R8) are **source-verified, not fixture-run** —
that gap is itself R10. Same rule as ever: where this file and the code disagree, the code wins.

**Also 2026-08-14 (workflow-completeness pass).** Walking the full end-to-end flow as a diagram
surfaced nine **missing-edge / dead-end** gaps — a released file with no publish target, a rejected
fix with nowhere to go, re-validate that may not re-score the whole file, and six scale/honesty
items. They are in **Phase W** (after Phase R). Unlike Phase R these were observed from the *flow*,
not confirmed in source this session — each names the file to confirm in first.

**Also 2026-08-14 (RunPod live verification).** Drove the live app end-to-end: **GPU vision is NOT
engaged** — alt-text falls back to a local filename-guess template and the AI-cost zone stays
`local (8/8)`, zero cloud, even after clearing the endpoint override. **R2 downgraded** from "env not
set" to "env set but runtime doesn't select RunPod" (the `runpod-api-key` secret not resolving is the
prime suspect → **R3**); **R12 is now VERIFIED FAILING**, not merely unverified. Both carry the exact
re-check steps.

---

## Phase R — Pilot readiness (observed 2026-08-14)

Cut ahead of releasing to three pilot users. Grouped: **R1–R3 ops-blocking**, **R4–R9 features**,
**R10–R13 testing**. Priority order for the pilot: R1, R2, R5.

### Ops-blocking (nothing else ships until these clear)

- [~] **R1 — Ship the wedged 3a + readiness deploy.** Frozen per-scan scope (#267) and the greyed
  not-ready SC matrix (#268) are **merged and green on `main` but not live** — the GitHub Actions
  deploy sits `pending` in the `deploy-production` concurrency group and never dispatches (the
  chronic stuck-Actions pattern, cf. P-era #239). Prod still serves `2026.8.13.5`. **Re-run to check:**
  `curl https://<ACP_FQDN>/healthz` (version), `gh run list --workflow deploy.yml` (runs sit
  completed/cancelled). **Fix:** `workflow_dispatch` + approve the `production` environment, or a
  manual `bash deploy/public/redeploy.sh` under `az login`.
- [~] **R2 — RunPod serverless vision: env is set, but the runtime does NOT select it.** The four
  RunPod env vars ARE now on `acp-app` (verified `az containerapp show` 2026-08-14:
  `ACP_VISION_PROVIDER=runpod_serverless`, `RUNPOD_ENDPOINT_ID=er7oqd0gq6ulsb`, `RUNPOD_API_KEY` →
  secretRef `runpod-api-key`, `RUNPOD_VISION_MODEL=Qwen/Qwen2.5-VL-7B-Instruct`) — so the *config*
  half is done. **But live testing (R12) proves vision still never reaches the GPU**: every AI call
  is recorded in the `local` processing zone, and a real 1.1.1 draft falls back to a filename-guess
  template ("this text model cannot see the image"). So `active_vision_provider()` is landing on
  local despite the env, which means `serverless_vision_provider()` is returning `None` — its guard
  is `not (eid and key)`, so the most likely cause is the **`runpod-api-key` secret not resolving to
  a valid key at runtime** (empty/absent → silent local fallback; ties to **R3**). **Fix / re-check:**
  `az containerapp secret list -g mdk-accessibility -n acp-app` (and `-n acp-worker`) to confirm the
  secret is populated with a valid key on BOTH apps, then read `providers.py:serverless_vision_provider`
  / backend logs for why it's `None`. Env being set is necessary, not sufficient — the secret is the
  open link.
- [?] **R3 — Rotate the RunPod API key.** It was pasted in plaintext into an ops chat. Decision/action,
  not code: RunPod → API Keys → revoke + reissue, update `~/.zshrc` and the `runpod-api-key` secret.

### Features (the four demo pillars + capability completion)

- [x] **R4 — Remediate drawer redesign.** Done. `RemediationInbox.jsx` is a 717-line two-column
  master/detail layout (35% queue + 65% workspace) matching the spec exactly: one dominant summary in
  the hero (deduped counters), `AssessmentScopeCard` replacing the old scope banner, no
  Approve/Reject on collapsed rows (`QueueRow` is select-only), lane chips (`r.laneShort`) visible
  on rows as quiet text, group-by-document default, workspace sections follow Problem → Evidence →
  How to fix → Decision, mode-specific actions ("Save edited fix" / "Reject & handle manually" /
  "Defer" / "Not applicable"), auto-advance on act. "AI Work Inbox" renamed — `reviewQueueNaming.test.jsx`
  asserts the term does not appear. *(Source-verified 2026-08-24.)*
- [x] **R5 — Continuous Monitoring: wire the Monitor tab to real source-staleness.** Done.
  `Monitor.jsx:133` calls `getSourceStatus(run.id)`, gated on `!SIM` so the demo keeps its
  illustrative surfaces. The drift state (`stale_count`, `untracked_count`, stale file list) feeds
  the real-staleness panel; any error leaves the panel empty rather than inventing changes; a scan
  with nothing trackable returns zero. *(Source-verified 2026-08-24.)*
- [x] **R6 — Phase 3b: per-scan scope chip + change-scope-and-rescan + impact estimate.** Done.
  `ScanScopeChip.jsx` reads from `run.scan_scope` (frozen criterion→formats map) and `run.scope`
  (file/source boundary), with a "change scope & re-scan" affordance that opens the review modal with
  a pre-populated impact estimate. Mounted in `Overview.jsx:428`. *(Source-verified 2026-08-24.)*
- [ ] **R7 — Phase 3c: per-user config (owner default + per-user override).** Governance model chosen
  ("owner sets a default, users can override"); not implemented.
- [ ] **R8 — WCAG capability completion (the 12 not-ready cells).** Source-verified against
  `remediation_capability.py` + `api/formats/*`, split 4/4/4: **~4 quick table-fixes** — detector ships
  but isn't declared (`xlsx 1.4.1`, `xlsx 1.4.11`, `xlsx 4.1.2`, `pdf 2.4.3` heuristic `/Tabs=/S`);
  **~4 real detector builds** — no detector (`pdf 1.4.1`, `pptx 1.4.11`, `pdf 1.4.11`, `pptx 4.1.2`);
  **3 appliers** — assessable, human-only fix (`2.4.4 pdf`, `3.1.2 xlsx`, `2.1.2 docx`); **~4 are
  legitimately N/A** (interaction SCs on static docs: `pptx 2.1.1/2.1.2/2.4.3`, `xlsx 2.1.2` — see the
  `ASSESSMENT_OVERRIDES` rationale). The quick-fixes are gated on R10.
- [ ] **R9 — (optional) Archive auto-fire.** Lifecycle Archive is override-only on real scans; auto-fire
  needs backend `superseded` detection (`retentionOf`, `FileDrawer.jsx:373`). Skip unless the demo wants
  Archive on the auto path.

### Testing / verification holes

- [x] **R10 — CI fixture-verification harness for the R8 understated cells.** Done. `tests/test_r10_fixture_cells.py`
  adds 9 tests covering xlsx 1.4.1, 1.4.11, 4.1.2 and pdf 2.4.3 — hand-crafted zip fixtures (stdlib only)
  for xlsx, `pytest.importorskip` guards for pdf (pikepdf/reportlab). All 9 pass in CI. *(Source-verified
  2026-08-24. PR #673 merged.)*
- [ ] **R11 — Multi-user / concurrency load test.** The durable Postgres queue + `owner_email` isolation
  is code-verified but not stress-tested with concurrent users — the exact 3-users-scanning-their-own-
  Drives pilot scenario. Re-run: a fan-out load harness against a staging estate.
- [~] **R12 — RunPod serverless E2E: VERIFIED FAILING in prod (2026-08-14, live drive of `acp-app`).**
  Not "unverified" any more — driven end-to-end through the live app and the answer is negative:
  **GPU vision is not engaged; alt-text silently falls back to local.** Evidence, all from the running
  app on `2026.8.14.1`:
  - A real `1.1.1` finding (`ACP_DOCX_01_01-issues.docx`) drafted to a **filename guess** with the
    literal banner *"Template only — this text model cannot see the image, so it guessed from the
    filename."* Every 1.1.1 finding routes to `Critical · manual authoring`, never an image-derived draft.
  - The **AI-cost processing-zone counter is the objective instrument**: it read `local (5)` before and
    `local (8)` after forcing fresh drafts — **8/8 calls local, zero cloud**. A RunPod call would register
    as a cloud zone; none ever did.
  - **Clearing the `ai_base_url` / `ai_vision_model` override** (Settings → "Use deploy default (clears
    both)") changed nothing — the count still climbed in `local`. So the override was NOT the cause; the
    provider selection is failing upstream (see R2). The override is now left cleared (deploy default).
  - Re-run this test the same way after any R2/R3 fix: force a `1.1.1` draft, then re-read the AI-cost
    zone — a genuine GPU call must show up as **cloud**, and the draft must be image-derived (🟡), not a
    filename template.
- [x] **R13 — Test the isolation-off invariant.** Done. `tests/test_isolation_invariant.py` adds 7 tests:
  3 isolation-ON (GOOGLE_CLIENT_ID set, ACCESS_CODE absent) and 4 isolation-OFF (both set — verifies
  `_owner()` returns `'demo'`, not the user's email). Asserts the `if ACCESS_CODE / elif GOOGLE_CLIENT_ID`
  gate in `app.py:127` behaves as documented. *(Source-verified 2026-08-24. PR #674 merged.)*

---

## Phase W — Workflow completeness (observed 2026-08-14, from the end-to-end flow)

These came out of walking the full "connected source → continuously governed content" flow as a
diagram and asking, at each box, *where does a real file (or a real reviewer) go next?* Every item
below is a **missing edge or a dead-end box** — a path the pipeline needs and does not visibly have.

**Read this differently from Phase R.** Phase R items were verified against code or ops state. These
were observed from the *flow*, not confirmed in the source this session — so each names the file to
**confirm in** before building. Where the code already has the edge and only the diagram omits it,
the item collapses to "document it"; where neither has it, it is a real build. The point of writing
them down is so the confirmation happens, not so anyone trusts the gap sight-unseen. Same rule as
ever: **the code wins over this file.**

Priority order: **W1, W2, W3** are the three a released file cannot currently route around; the rest
are scale and honesty polish.

### The three a file cannot route around

- [x] **W1 — Where does the remediated file actually land? (the missing terminal).** Done.
  `Publish.jsx` writes the remediated copy to Blob storage and offers an optional Drive mirror via
  `releaseDestination()`. Download-only, governed-store, and replace-at-source are all explicit paths;
  the certified artifact is served from the remediated-doc store. *(Source-verified 2026-08-24.)*
- [x] **W2 — A rejected fix dead-ends.** Done.
  `Remediate.jsx:313/529` maintains a `rejectedItems` state that routes rejected findings back to the
  HITL inbox for a different fix lane, rather than leaving them silently stalled. *(Source-verified 2026-08-24.)*
- [x] **W3 — Re-validate must re-score the WHOLE file, not just the fixed criterion.** Done.
  `api/handlers.py` `_rescore_file` (line 1906) calls `_analyse_and_persist_one` with the full detector
  set for all in-scope criteria, then calls `refresh_scan_aggregate` — not just the touched SC. A file
  can be sent backward into the queue if any criterion regresses. *(Source-verified 2026-08-24.)*

### Scale & honesty polish

- [x] **W4 — UNCHECKED is a dead-end box.** Done.
  `DispositionControl.jsx` and `FileDrawer.jsx` provide disposition lanes for UNCHECKED/GAP/AT criteria:
  `out_of_scope` and `attest out-of-band` are both available edges, so UNCHECKED is no longer terminal.
  *(Source-verified 2026-08-24.)*
- [x] **W5 — Conditional release can't graduate.** Done.
  `Publish.jsx:124/201` has conditional release graduation UI; `graduation.js` defines CONDITIONAL/FULL
  states with promotion logic so a file can graduate conditional → fully certified without a full
  re-scan once held items are remediated. *(Source-verified 2026-08-24.)*
- [x] **W6 — Surface AI provenance on the review card (the silent-fallback made visible).** Done.
  `EvidenceCard.jsx:280` shows the real AI processing zone (RunPod cloud vs local CPU) sourced from
  the per-call ledger, giving reviewers the signal to weight their review. *(Source-verified 2026-08-24.)*
- [x] **W7 — No operational-failure lane.** Done.
  `FailureLane.jsx` implements the operational-failure lane with retry → dead-letter → count display.
  `Monitor.jsx:353` mounts `FailureLane` so job failures (corrupt file, expired token, unreachable
  source) are visible and actionable rather than silent. *(Source-verified 2026-08-24.)*
- [x] **W8 — Batch action for identical findings.** Done.
  `RemediationInbox.jsx:272` has an "apply to all matching" batch action off a reviewed finding; line
  27 normalizes SC/rule keys so identical findings across files are correctly grouped. *(Source-verified 2026-08-24.)*
- [x] **W9 — Time-based re-validation, not only change-based.** Done.
  `api/core.py:556` runs a background scheduler that fires periodic re-scans at `interval_minutes`,
  independent of source drift. `Monitor.jsx:277` exposes `getSchedule`/`putSchedule` for configuring
  the time-based trigger. *(Source-verified 2026-08-24.)*

---

## Phase 0 — CLOSED 2026-08-09 (all ten; P0.10 is a decision, not code)

All nine build items are done. The two investigations that headed the list — P0.1 and P0.2, the
ones whose wrong answer is a patient-data incident rather than a missed finding — are answered in
writing, in `audit-owner-isolation.md` and `audit-langfuse-phi.md`. Both are worth reading for the
same reason: **each found the opposite of what the item predicted.** P0.1 expected an IDOR via a
request parameter and found the parameter path clean and a different, real disclosure beside it;
P0.2 expected prompts full of PHI going to a third party and found prompts reduced to a count and
Langfuse self-hosted. An investigation that confirms its own premise is the one to distrust.

Three items. The first two are investigations that could change what you tell the customer; the
third is the correctness fix with the widest blast radius.

- [x] **P0.1 — Is `owner` derived from the session or the request?** **The session** — and asking
  the question found a real hole next to it. `_owner()` reads `request.state.user_email`, written
  in exactly one place from a verified GIS token; no query parameter, path segment, header or body
  field reaches it. That much the 2026-08-08 audit had already established.
  **But the remediated-download route was not in any foreign-access test, and it was exploitable
  (#209).** `get_remediation_urls` had no owner predicate; the blob read beside it *was* scoped, so
  a foreign document came back `None` and fell through to a Drive mirror URL from a row the caller
  had no right to. A correct control created the path to an incorrect one. Measured with the real
  gate: an allow-listed non-owner got `307 -> the owner's Drive link`, with the owner's own request
  succeeding in the same run. The same fall-through was also an oracle — `307` vs `404` revealed
  which documents a scan contained.
  Fixed in two independent places, each sufficient alone and each with its own test: ownership
  resolved at the route (404 as `"scan not found"` verbatim), and an owner predicate filtering **in
  SQL** so a foreign row is never read into memory.
  *Path traversal — the other thing that audit left uncovered — was checked and is safe:* `..`
  reaches the blob key, but Azure blob names are flat strings and never resolve it. Pinned anyway,
  since that is a property of the storage backend rather than of this code.
  *Isolation-off is now loud at startup.* The trap worth knowing: `ACCESS_CODE` and
  `GOOGLE_CLIENT_ID` are an `if`/**`elif`**, so setting an access code on a deployment that HAS
  Google configured does not add a second factor — it stops `user_email` being stamped at all.
  See [audit-owner-isolation.md](audit-owner-isolation.md).

- [x] **P0.2 — What does Langfuse capture in production?** **Not prompts — the premise was wrong,
  in our favour.** ACP does not use Langfuse auto-instrumentation; `api/lf.py` hand-builds every
  span and sends `prompt_chars`, a count. Document text and OCR output never leave. PII spans send
  types and counts, never matched values.
  Four content-derived fields did leave: **filename** (every trace, unbounded), model completion
  (1500 chars), approved value (500), and the reviewer's free-text note (unbounded). The note is
  fixed (#210) — sent as `note_chars`, because truncation would have been theatre: PHI in a note
  sits at the front, so any cap that leaves it readable leaves the identifier intact.
  **And Langfuse is self-hosted in both deployment shapes** — a compose container or an
  ACP-operated Azure Container App, never Langfuse Cloud. So there is no third-party disclosure and
  the BAA question is much narrower than assumed; what remains is retention inside our own
  boundary. See [audit-langfuse-phi.md](audit-langfuse-phi.md).
  **Two decisions left, both in P0.10 below.**

- [?] **P0.10 — The two Langfuse decisions P0.2 surfaced, plus one from P0.1.** Not code, and not
  closeable by anyone but you.
  * **Filenames in traces.** The only field flowing on every scan, and the largest remaining
    exposure by volume — in a hospital estate the filename carries the patient
    (`Smith_John_MRN0114233_intake.docx`). Hashing it, or keeping extension plus a per-scan index,
    removes the identifier; both make a trace harder for a human to skim. That trade is the
    decision.
  * **`deploy.sh` defaults to the shared demo project's Langfuse host and public key.** A
    deployment that does not override them traces into the project the demo views.
  * **Should production refuse to boot in Basic-auth mode?** The right fail-closed default for
    PHI, and it can lock out a running deployment — which is why #209 made it loud rather than
    fatal.

- [x] **P0.3 — Make the file-type filter reach the scanner.** Done. `scan_scope` now gates what
  is READ, not only what is scored: `assessment_policy.file_in_scope` decides per file and
  `scanner._list` drops the rest before `_download` ever sees them.
  **Applied at the dispatcher, not the four enumeration sites the proposal listed.** Local,
  SharePoint, Drive-folder and whole-Drive all converge on `_list`, so one gate covers every
  source and any source added later — a stronger guarantee than four call sites kept in step.
  What it claims is narrower than "not listed": an out-of-scope file's *name* still comes back
  from a source the operator connected on purpose; its *content* is never downloaded, opened,
  rasterised, OCR'd, cached or traced. Content was what was being read, so content is what
  stopped.
  The HTML exemption and `skipped_out_of_scope` are both in, the latter surfaced in the Discover
  sentence and feeding `isNarrowScope` — gated on the count, not the setting, so a `.docx` scope
  over an all-Word estate raises no warning about nothing.
  *Verified by disabling the gate and re-running: 4 of 12 tests fail without it, including the
  load-bearing one, which asserts on the FETCH rather than the file list — a list-only assertion
  passes against the old behaviour too, since the old list was filtered downstream anyway.*
  All three of the proposal's "consequences" are now closed — see P0.4, P0.5 and P0.6.

- [x] **P0.9 — A finding's position survives persistence whichever key the detector used.** Done.
  `issue_records.location` was written from `i.get("location")` at both INSERT sites. The vendored
  .NET rules write `location`; several first-party Python detectors write `locator` — so **every
  Python-detected finding was stored with `location` NULL**. The finding survived; the ability to
  point at the thing it is about did not, and that column is what a review card reads. Measured:
  saving one of each stored `"docx:image:3"` for the .NET finding and NULL for the Python one.
  **A fallback, not a rename** — the keys are not synonyms elsewhere. A `locator` is a resolvable
  write target (`apply_alt.parse_locator` turns it back into an element); `location` is a position
  string for a human. On a *finding* they answer the same question and the locator is the better
  answer, so it is used only when `location` is absent, and nothing consuming `locator` as a write
  target is touched. One accessor serves both INSERT sites, so it cannot be applied at one and
  forgotten at the other — which is the shape of the bug it fixes.
  *Noted while testing, deliberately not folded in:* findings are written as `ruleId` and read
  back as `rule_id`. A second instance of the same split, but load-bearing — the read shape is the
  row shape and every consumer expects it, so renaming is its own change with its own blast radius.

- [x] **P0.8 — An empty heading is detected (2.4.6).** Done. The outline walk read `pStyle` refs
  and never the heading's text, so an empty `Heading` paragraph passed every check ACP had: in
  the outline (no pseudo-heading finding), breaking no level sequence (no skip finding), and with
  no runs to fail contrast on. It produced **zero** findings.
  Screen readers offer a heading list as the primary way to navigate a long document; an empty
  entry announces nothing, so the reader is told a section exists and can neither identify it nor
  tell whether they have missed content.
  Exempt: a heading whose content is an **image**. Its problem, if any, is 1.1.1's, and reporting
  it here would report one defect twice — the same reasoning `_link_purpose_finding` already
  applies to a hyperlink wrapping a drawing. Empty **body** paragraphs are untouched; blank
  spacers are everywhere in real documents and flagging them would bury the real finding.
  *With this in, the labelled corpus reaches macro-F1 **1.00 on both lanes**, micro recall 1.00,
  precision 1.00, zero false passes and zero false positives — and the five long clinical
  documents add no false positives either.*

- [x] **P0.7 — Exceeding the OCR image cap is reported, not silent.** Done. `_MAX_IMAGES`
  (`ACP_OCR_MAX_IMAGES`, default 30) bounds how many embedded images are OCR'd per document, and
  exceeding it produced no signal: a 35-image document returned exactly 30 image-of-text findings
  and nothing said the other five were never looked at — output indistinguishable from a document
  whose last five images are clean.
  **The cap was not raised, deliberately.** Measured at ~0.1s per image on a synthetic fixture
  (30 ≈ 3s, 500 ≈ 51s), so 30 is conservative — but a higher number still truncates *silently* at
  the new number, and picking a new default is a scan-time decision for every customer taken on
  evidence from synthetic images that are easier than a real scanned page. The knob already
  existed; what was missing was any way for an operator to know they needed it, so the finding
  names it.
  Advisory (`REVIEW`), not blocking: the honest claim is not "these images fail" — nobody read
  them — it is "this criterion was not fully checked here". Emitted from the 1.4.5 pass only, since
  both rules walk the same capped list and 1.4.9 is AAA, dropped at the AA target most scans use.
  *The load-bearing test is a CLEAN over-cap document: with textless images the scan finds nothing
  at all, so before this its output was empty and identical to a fully-checked clean file.*

- [x] **P0.6 — The report's scope-of-assertion names the documents it never opened.** Done.
  `_scope_section` is the report's guard against its own headline number, and every narrowing it
  stated was by CRITERION ("no check was run for 2.4.3 on a PDF"). None was by DOCUMENT — so once
  the file-type scope gates what is read, a whole class of files is absent from the report
  entirely: not failing, not passing, not evaluated, never opened, and unmentioned.
  A conformance report that lists the criteria it skipped but not the documents it never saw
  understates its own boundary in the flattering direction, which is the exact failure the rest
  of that section exists to prevent — the auditor asking "does this cover the estate?" gets
  "yes" from silence.
  The facts come from the **scan's own recorded scope**, not the live setting: a report is a
  statement about what happened, and reading the current setting would let an already-issued
  report re-describe its own past when someone changes the scope.

- [x] **P0.5 — Scan diffs are scope-aware (ADR 0009).** Done. Two failures, one cause: a score is
  computed over the in-scope findings, so the same unchanged document scores **60** under a wide
  scope and **75** with one criterion in scope. Diffing across a scope change therefore reported
  every document as **improved** — an operator who narrowed the scope was congratulated on
  progress that did not happen — and every file the new scope excluded, never read and so absent
  from `file_records`, landed in `removed` as *"45 documents disappeared"*.
  `scan_runs.scope` now carries the criteria scope alongside the discovery boundary (no
  migration — it rides in the existing JSON), and `get_scan_diff` compares what each scan
  actually measured.
  **Compared per format, not globally.** A scope change that only touched PDF criteria leaves
  every `.docx` score computed over exactly the same criteria, so those deltas are still real —
  treating any scope change as poisoning the whole diff is the obvious fix and it discards the
  comparison an operator most often wants.
  Incomparable files are **reported, not dropped** (`incomparable`), files the scope excluded are
  `not_read` rather than `removed`, and the radar says the scope changed — suppressing the
  numbers silently leaves a reader concluding nothing changed, which is the same wrong answer
  from the other side. "Nothing got worse" is downgraded to "nothing got worse among the
  documents that could be compared" when anything was excluded.
  *Verified by disabling the scope-awareness and re-running: the two headline tests fail.*

- [x] **P0.4 — An incrementally-reused analysis is re-scored under the current scope.** Done, and
  **the diagnosis in the proposal was wrong**, which is worth recording because the wrong version
  reads as plausible. It said incremental fingerprinting "caches file lists" and that a scope
  change would make the first narrowed scan "return the old population". There is no file-list
  cache — `_list` runs fresh on every scan, so P0.3 already governs the population.
  The real defect was one level down and quieter. `find_prior_analysis` (ADR 0011) reuses a
  file's analysis across scans gated on owner + `drive_file_id` + checksum + `rubric_hash`, and
  returns the stored `score` / `compliant` / `skipped_rules` — all of which are **scope**-
  dependent, since `_scoped_for_scoring` decides what `Rubric.assess` ever sees. Nothing gated on
  scope. Measured: one `.docx` with a 1.1.1 and a 1.3.1 finding scores **60** unscoped and **75**
  with only 1.1.1 in scope, and the reuse handed back 60 — fifteen points wrong, silently, and
  looking exactly like the scope had done nothing.
  Same class of staleness `rubric_hash` already guards, in its own words: *"a stale analysis under
  an old rubric is not valid evidence once the rule set has changed."* A stale score under an old
  scope is not valid evidence either.
  **Re-scored, not invalidated.** Invalidating would discard the reuse for every file in the
  estate and re-run the engine over documents that have not moved. The full issue list comes back
  *with* the reuse and scoring is a pure function over it, so the score is recomputed for free
  while the download, engine and OCR stay skipped — which is what `_scoped_for_scoring` already
  promised: *"re-reporting the same scan under a different scope needs no re-scan."*

---

## Phase 1 — before Monday

- [ ] **P1.1 — Walk v2 on a cleared browser.** `.docx` ticked by default; Discover filtered;
  Assess/Remediate/Overview agreeing. Everything verified so far has been static (bundle
  contents, minified strings, traffic weights). localStorage must be cleared first or the old
  config masks the change.
- [ ] **P1.2 — Rehearse the DOCX numbers.** Still open (it is a rehearsal, not a build) but the
  figures moved — **rehearse these, not the ones this line used to carry**:
  **15 of 15** Core-17 criteria in scope for docx have a lane; none returns `NOT_EVALUATED` (the
  "3 are not assessed at all" clause is gone — see P2.4) · **4 can certify a PASS** (1.3.1, 1.4.3,
  2.4.2, 3.1.1) — unchanged, and the number most worth saying precisely · remediation lanes over
  those 15: **6 ⚡ auto · 8 🤖 assisted · 1 👤 human**.
  The honest sentence pairing them: *every criterion is assessed, most are fixed or drafted for
  you, and four are ones a clean scan can certify* — the other eleven are reported as reviewed,
  not passed. Source: `docs/capability-report.md`, and `remediation_capability.CAPABILITY["docx"]`
  is the authority if the two disagree.
- [x] **P1.3 — Say the Ontology gap out loud.** Said, and said in the PRODUCT rather than only
  here, which is where it mattered: on an unclassified estate Discover now states that department
  and sensitivity are not collected, and OMITS the exposure-and-risk chart instead of rendering it
  at zero. That chart read "100% internal" with every risk flag at 0 — each number true and the
  reading false, since *"0 legal-hold"* asserts an estate holds no documents under legal hold,
  which is a finding nobody obtained, on the screen a compliance reader opens to find them.
  The port/defer/drop decision on `Ontology.jsx` (v1-only; the `ontology.js` data layer survives)
  is still open and now belongs with P2.3, which is blocked on the same missing thing: a
  scan-derived source for classification.
- [?] **P1.4 — Vision default.** `moondream` scores **0/6 facts and asserts a false year** on a
  real notice (`docs/local-model-evaluation.md`). `qwen2.5vl:7b` scores 3/6 at 4.4s. Blocked on
  the 8 GiB Consumption ceiling that forced moondream — ADR 0022 requires the CPU floor stay
  available, so this is an infrastructure decision, not a config change.

---

## Phase 2 — next week

- [x] **P2.1 — Corpus ground truth: 5 → 61 pairs.** Done — **61 pairs mapped.** `config/rule-catalog.json`
  now covers all xlsx, pdf, and pptx rule IDs in addition to the original DOCX entries; every rule
  in the catalog is tied to a WCAG SC. Alongside the mapping, 34 new `docs/rules/*.md` stubs were
  written to satisfy the ADR 0002 §4 contract, and `frontend/src/ruleDetails.js` was regenerated to
  include all 70 rules. Merged as #683 (squash `3675c088`) 2026-08-24.
- [x] **P2.2 — Reconcile the three scope editors.** Resolved by REMOVAL rather than by the
  reconciliation this item asked for, which is why it is worth writing down rather than just
  ticking. The item read: *"`ScanSetup`, `FileTypeConfig` and `ScanScope` each write all of
  `scan_scope`; last touched wins."* Two of those three are now mounted nowhere — `ScanScope` came
  off Discover with the criterion picker and `FileTypeConfig` off Settings — so there is no longer a
  race to arbitrate. Verified 2026-08-21 against `origin/main`: the only surfaces that write
  `scan_scope` are `ScanSetup` (on Overview) and `AssessSetup` (in App), and they own different
  axes. Both retired components are kept in the tree per CLAUDE.md; if either is mounted again this
  item comes back with it.
- [ ] **P2.3 — Document-type scoping. BLOCKED, and this row's premise was wrong.** It read: *"the
  ontology data already exists."* It does not. Verified against `origin/main` on 2026-08-21:
  `file_records` (`store.py:70`) has no `department` and no `tags`; `get_scan` (`store.py:1752`)
  projects that table alone and joins nothing; `documents` is the only table carrying `department`
  and `store.py:4647` says outright that *"department has no scan-derived source yet, so on most
  estates that bucket IS the estate"*; `store.py:1902` adds that department-selector scope rules
  therefore do not resolve. So on every real estate `f.department` is undefined and `f.tags` is
  empty — Discover's whole triage surface was SIM-only, which is now said on the screen rather
  than rendered as zeros (`classificationData.js`).
  **The blocker is a scan-derived source for classification, not a scoping control.** Building
  "assess only legal-hold" on top of this would scope a customer's estate by an empty column. The
  nearest real source is SharePoint's own managed metadata / content types / sensitivity labels —
  listed in `docs/sharepoint-gaps.md` as a build within the read-only scopes (`listItem/fields`).
  Do that first; the scoping control is small once the data is real.
- [x] **P2.4 — The three unassessed DOCX criteria.** Done — all three built rather than disclaimed.
  1.4.1 and 1.4.11 landed as declarations with guided lanes (#202) and then prefilled proposers
  (#203), which moved both from `human` to `assisted`: the criterion is editorial, but the SIGNAL
  ACP detects is exact — restore the removed underline; use this computed shade. 2.1.2 landed
  (#206) as `human`, and there it is a conclusion rather than a staging post: keyboard-trap
  behaviour is runtime and absent from the file, so there is no signal to prefill from.
  **Every one of the 15 Core-17 criteria in scope for docx now has a lane; none returns
  `NOT_EVALUATED`.** 4 can certify a PASS (1.3.1, 1.4.3, 2.4.2, 3.1.1) — unchanged, and the honest
  number to rehearse in P1.2.
- [x] **P2.5 — The 14 pairs with no recorded remediation decision.** Done — **0 remain.** Measured
  over the 96 detectable pairs in `store.RULE_FORMATS`: every one now carries an explicit
  remediation lane, so `mode_for()`'s `human` default is no longer standing in for an absent
  decision anywhere. The last of them was docx 4.1.2 (#208), which turned out to be understating
  rather than missing — the deterministic fixer already ran, gated on 3.3.2's scope alone and
  credited only to 3.3.2.

---

## Phase 3 — the structural ones

- [ ] **P3.1 — Vendor the PDF engine.** `ACP_PDF_ENGINE` is external, so 13 of 61 pairs are
  unmeasurable locally *and* skipped in CI (`tests/test_scan.py`, `test_remediation_capability.py`).
  A fifth of the matrix nobody can test. ADR 0012 vendored the Office analysers the same way.
- [ ] **P3.2 — Accessible generated PDFs.** ACP's own rule `pdf.tagged` (1.3.1) flags untagged
  PDFs, and neither generator emits a structure tree — jsPDF cannot at all. An accessibility tool
  shipping non-conformant PDFs is a credibility problem. Architectural: move report generation
  server-side, or post-process.
- [ ] **P3.3 — Healthcare hardening.** Encryption with customer-managed keys; retention and
  deletion paths for a BAA; confirm nothing logs document content.
- [ ] **P3.4 — Power BI export.** Given the data is in Postgres, a read-only view plus DirectQuery
  is likely cheaper and better than an export feature.
- [x] **P3.5 — `vite@8` / `esbuild` CVEs.** Done. `frontend/package.json` upgraded vite `^5.4.11` →
  `^8.2.2` and `@vitejs/plugin-react` `^4.3.4` → `^5.2.0`. Fixes GHSA-67mh-4wv8-2f99 (moderate esbuild)
  and one high CVE. Dev-only; vitest 4.1.9 compatible with vite 8. *(Source-verified 2026-08-24. PR
  #672 merged.)*

---

## Phase 4 — the local-model programme

From the ACP Local Model Evaluation PRD, filtered to what the 2026-08-08 measurements support.
Items the PRD proposes that are **not** here are listed at the end with the reason — a backlog
that silently drops half a proposal is worse than one that argues with it.

**Read P4.0 first. It is the prerequisite for every other item in this phase**, and it is the one
thing the PRD does not mention.

- [ ] **P4.0 — Decide whether an AI-assessed lane may auto-apply, and under what evidence gate.**
  Measured, not predicted: `score_remediation.py` scored `qwen2.5vl` **3B, 7B and 32B and
  `moondream` at an identical 50% VRR / 0% regression / 0% damage**. That is structural. No
  ungrounded vision draft is ever auto-applied — the honesty split routes all of them to
  `proposals` — so the model changes what a reviewer *sees*, never what the document *gets*.
  **Until this gate moves, every model, prompt, evidence-mode and routing experiment below
  returns the same table**, and a sweep across four models will read as "parameter count does not
  matter" when it actually means "no model output reached a document."
  The precedent already ships: grounded (OCR-anchored) alt auto-applies today, ungrounded does
  not. Generalising *that* mechanism is the decision, not inventing one.
  *Effort: a decision plus an ADR. `[?]` — needs a decision, not code.*

- [ ] **P4.1 — Split the eight review-lane SCs by whether the negative is deterministically
  provable.** The PRD treats all eight as one problem. They are two.
  **Group A — provable** (1.1.1, 2.4.4, 3.1.2, 4.1.2): "does every image carry a non-junk
  `descr` or a decorative marker?" is a yes/no over the OOXML, and ACP answers it at **1.00
  recall / 1.00 precision** today with no model involved. An LLM cannot improve the PASS decision
  here; it can only add a semantic-quality opinion, which is a different and less verifiable
  claim. Group A needs an ADR, not an experiment.
  **Group B — judgement** (1.3.2, 1.3.3, 1.4.5, 2.4.6, and the hard half of 1.1.1): is the
  reading order *meaningful*, is this image of text *essential*, is this heading *descriptive*,
  is this alt text *correct*. Only here does model quality decide the answer, and only here do
  the PRD's experiments earn their cost.

- [ ] **P4.2 — Corpus density: the 99% PASS-precision gate needs ~300 observations per SC, not
  20–30.** By the rule of three, *n* trials with zero observed failures bound the true rate at
  roughly `3/n` at 95% confidence. The PRD's proposed 20–30 fixtures per SC licenses a claim of
  **≤10%**, an order of magnitude weaker than the gate it is meant to clear — and it would read
  as validated. `score_assessment.py` prints this ceiling on every run for exactly that reason.
  Not a blocker: the fixtures are generated, so this is parameterising `gen_sc_corpus.py`'s
  builders to sample densely around each decision boundary rather than hand-writing 300 files.

  **[~] Half done (#207), and the half that landed shows why the other half may not be reachable
  this way.** `scripts/gen_sc_sweeps.py` samples densely where the input space is genuinely rich —
  40 greys across 4.5:1 for 1.4.3, 19 passage lengths across the 12-word floor for 3.1.2, 16
  junk-alt strings for 1.1.1. All six exercised SCs score F1 1.00 with zero false passes, and
  1.4.3 is exact at every one of the 40 greys. 2.4.2 and 3.1.1 are deliberately NOT swept: their
  input space is two or three discrete states, so copies would inflate the denominator and prove
  nothing.
  `score_assessment.py` now reports the ceiling **per criterion**, which is the less flattering
  number and the only honest one — pooling bought 1.4.3 nothing, since a detector that mishandles
  a grey is not vindicated by fixtures exercising langdetect. Per SC: **13.0% / 23.1% / 23.1%**,
  densest n=23 against the ~300 a 1% claim needs.
  **Two cautions the work itself produced.** More fixtures are not automatically more
  observations: the first version asked for 40 samples across a 21-value range and emitted 21
  files with 40 manifest rows — an inflated denominator, generated by the module whose docstring
  warns about inflated denominators. And consecutive samples share almost everything (one grey
  step apart), so even at n=300 a swept criterion would bound *"the detector mishandles some input
  in this band"*, not *"ACP is wrong about an arbitrary document"*. **Closing the remaining gap
  needs many genuinely distinct documents per criterion, or a narrower claim scoped to the band
  actually sampled — not more of the same shape.**

- [ ] **P4.3 — Evidence modes A–E; find the minimum viable evidence package.** (PRD §11.) The
  highest-value experiment in the document and the cheapest, because ACP already emits most of
  the package — findings carry `locator`/`location`, OCR text in `detail`, and the OOXML walk is
  `formats.office.images`. Compare full-page render / object crop / crop + context / crop +
  deterministic evidence / all of it. Blocked on nothing.

- [ ] **P4.4 — Independent verification: the generator must not approve its own remediation.**
  (PRD §20.) Cheap, high safety value, and needs no policy change to *measure*. Prefer
  deterministic verification wherever it is complete — 3.1.2 is fully closable today (set
  `w:lang`, re-run langdetect on the span, no model prose trusted), 2.4.4 is partial (uniqueness
  yes, accuracy-to-target no), and 1.1.1 is not verifiable at all, which is the asymmetry that
  matters: **a wrong alt does not merely fail, it silences the detector.**

- [ ] **P4.5 — Extend the adversarial fixtures.** (PRD §13/§14.) Partially built:
  `gen_sc_corpus.py` already carries decorative-that-looks-informative, logo-vs-image-of-text,
  descriptive-link, correctly-marked-`fr-FR`, sub-floor language segments and both sides of the
  contrast boundary. Missing from the PRD's list and worth adding: product names that scan as
  foreign language, misleading captions, and surrounding text that partially duplicates an image.
  Correct abstention is scored as correct, not as a miss.

- [ ] **P4.6 — Confidence calibration, with the sample-size caveat from P4.2.** (PRD §17.) A
  local model's self-reported `"confidence": 0.97` in a JSON blob is not a calibrated
  probability and must never be used as one. Measure empirical precision per bucket, keep PASS
  and FAIL thresholds asymmetric, and note that each bucket needs its own *n* before it means
  anything.

- [~] **P4.7 — Reproducibility metadata on every recorded result.** (PRD §26.) Model, revision,
  quantisation, runtime, prompt version, fixture version, hardware, temperature, seed.
  Phase 1 done — PR #693: `proposal()` factory now stores a structured `_model` key alongside
  the prose `source`; `judge_drafts.py --out` wraps results as `{"metadata": {"seed", "judges",
  "run_at"}, "results": [...]}`. Remaining: `temperature` + `prompt_version` columns in
  `ai_calls` (needs schema migration).

- [x] **P4.8 — Reviewer hand-off payload.** Done. When ACP escalates it now hands the reviewer the
  SC, the object, the deterministic evidence, the reason for uncertainty (`why_review`) and the
  proposed fix, so a human resolves the remaining ambiguity instead of repeating the assessment.
  The per-file and per-rule progress line landed with it (`api/activity.py`), including the
  concurrent case — the channel renders the oldest in-flight entry plus "(+N more in progress)"
  rather than interleaving them. **It was never blocked on P4.0**, which is why it was worth
  doing first: it is the one item on this list whose value does not depend on any policy question
  being settled.

- [x] **P4.9 — Regression detection across all Core-17, not just the target SC.** (PRD §22.)
  Built: `score_remediation.py` computes fixed / unresolved / regressed over every criterion, and
  disqualifies a fix that loses a paragraph, table, section or media part regardless of what the
  re-scan says. Media parts are counted from the zip because `Document.inline_shapes` misses
  header, footer and floating images — the consent fixture's only image is in `word/header1.xml`.

### From the PRD, deliberately not scheduled

- **North-star framing.** "Maximise AVRR while minimising HER" puts autonomy in the numerator and
  safety in a footnote. Invert it: the target is *the highest autonomy achievable subject to a
  false-PASS bound*, so the constraint cannot be traded away by a good week on the other metrics.
- **§9 model-discovery CLI, §7/§8 registry across ONNX/vLLM/GGUF.** Model *availability* is not
  the bottleneck — P4.0 is. Ollama already covers everything testable today. Revisit if a
  specific model is wanted that Ollama cannot serve.
- **§29/§30 fine-tuning and holdout splits.** The PRD defers these itself and is right to. Worth
  stating the bar plainly: the baseline to beat is a deterministic engine at **macro-F1 1.00
  (deterministic lane) / 0.96 (review lane)**, not a naive-prompt LLM.
- **§31 CLI, §32 dashboard, §33 Pareto frontier.** Reporting infrastructure ahead of a result to
  report. `score_assessment.py` and `score_remediation.py` already print the decision surface.
- **§25 hardware profiles.** Mostly moot for now — Azure has zero GPU quota on a CSP-managed
  subscription, so "local Apple Silicon" is the only profile that exists. Revisit with I.1.

---

## Phase 5 — silent under-reporting, found while building elsewhere

Added 2026-08-09. None of these was on the original list, and they share a shape worth naming:
**each is a place ACP reports nothing and looks clean.** A detector that over-reports gets fixed
because somebody complains; one that under-reports is indistinguishable from a compliant document.
That is the failure mode the 2026-07-30 capability-grid exercise found nine of, and these are the
ones currently visible.

Worked 2026-08-09 evening. Three of the five closed, two blocked on installs. Each was
measured before it was touched — the fixture ran red on the old code, so the gap is proven, not
argued.

- [x] **P5.1 — Link purpose (2.4.4/2.4.9) is judged in headers, footers and notes.** Done (#214).
  `office_structure.docx_checks` read `word/document.xml` alone, so a "click here" in a page footer
  produced ZERO findings — measured with a clean-body control plus a vague link isolated in each of
  header, footer, footnote and endnote (all four silent before, all caught after). Fixed by
  `_docx_hyperlinks` walking every story part, each resolving its own `_rels`.
  **Scope, stated honestly:** this closes LINK purpose across the parts. The heading walks (1.3.1
  pseudo-heading, 2.4.6) stay body-only (a heading styled into a footer is rare and low-value), and
  1.4.3 text contrast is out of reach here — its docx detector lives in the vendored .NET engine.
  **Found while doing it:** 1.1.1 alt text was NOT a gap — `formats/office/images.py` already globs
  `word/(document|header\d*|footer\d*).xml`, so header/footer logo images without alt were already
  caught. The named "1.3.1 / 2.4.4 / 1.4.3" turned out to be really just 2.4.4 in Python.
- [x] **P5.2 — Tracked deletions no longer leak into extracted text.** Done (#215). Only one of the
  two feared directions was a live bug: `pii._ooxml_text` tag-strips the word parts, turning
  `<w:delText>` (struck-out content a reader never sees) into words — so PII detection flagged
  DELETED phone numbers and 3.1.2 scored deleted prose. Measured with a document carrying a kept
  line, a tracked insertion and a tracked deletion; the deletion leaked. One surgical line removes
  `<w:delText>` before flattening. Insertions correctly stay (ordinary `<w:t>`), and the regex
  detectors were already safe (they read `<w:t>`, never `<w:delText>`). Stance: extract as
  tracked changes ACCEPTED — insertions in, deletions out.
- [?] **P5.3 — Word round-trip via LibreOffice.** BLOCKED on an install, not on design. LibreOffice
  is not present on the build host (no `soffice`, no `/Applications/LibreOffice.app`), so the
  independent round-trip cannot run here. Unblock: install LibreOffice (headless is enough), then
  build the round-trip check. Still the cheapest external validation available — worth doing once
  the binary is there.
- [?] **P5.4 — Mutation testing on the detector modules.** BLOCKED on tooling. No mutation library
  is installed in the venv (`mutmut` / `cosmic-ray` absent), and adding one plus running a campaign
  is a dev-dependency + CI-time decision, not a quiet addition. Unblock: decide whether to vendor a
  mutation runner and where it runs (it is slow), then point it at `office_structure` / the docx
  detectors. The reasoning stands: F1 1.00 bounds only the fixtures we thought to write.
- [x] **P5.5 — v2 capability table synced to the backend, and guarded.** Done (#216), and it was
  bigger than filed. The item said "no docx 4.1.2 row"; measuring found FIVE drifted cells —
  docx 1.4.1/1.4.11/2.1.2/4.1.2 missing on both axes, and xlsx 3.1.2 carrying a WRONG value
  (`assisted`, should be `human`). The four docx rows are exactly this session's lane additions
  (#202/#203/#206/#208): each updated v1's `capability.js` and none updated v2, because v1 has a
  backend sync guard and v2 had none. The fix is that guard —
  `tests/test_capability_frontend_v2_sync.py`, mirroring v1's — which failed on both axes first and
  passes after the sync, so the drift cannot silently return. v2 lane totals now match v1 (6⚡8🤖1👤).

## Infrastructure — parallel track

- [ ] **I.1 — Azure agent pool.** Blocked on an admin granting it. All 14 merges on 2026-08-08
  bypassed Azure because 16 jobs were stuck behind the org's single parallel slot. Draft email
  written; agent built and merged (#183).
- [ ] **I.2 — Fix the production approval gate.** The UI approval silently failed three times
  today; the API worked instantly every time. Worth understanding before it blocks a release
  nobody can approve.
- [x] **I.3 — Raise `num_predict` for 32B.** Done. Raised ceilings in `api/ai.py` (120→200, 140→250,
  400→800, 220→400, 200→400) and `api/providers.py` (128→200). Root cause: reasoning models emit a
  thinking pass before answering — the old caps ran out mid-thought, returning empty responses. Since
  `num_predict` is a ceiling, raising it costs nothing when the model finishes early. *(Source-verified
  2026-08-24. PR #675 merged.)*

---

## Closed on 2026-08-09 — 21 PRs (#202–#222)

- [x] **Chain B is automatic (#220, #221, #222).** A merge to `main` now deploys itself: the
  Google ADC became optional when GIS per-user sign-in is set (#220), the trigger fires on CI
  *success* via `workflow_run` rather than racing the push (#222 fixed #221's own bootstrap), and
  the SharePoint roadmap was synced to the code that already shipped it (#221). See
  `docs/pipeline.md`. **In review, not yet merged:** the ingress traffic-routing fix (#223, the
  root cause of every failed deploy since Aug-8 — a blue-green run left the app in Multiple
  revision mode) and robustness tests for the migrated detectors (#224).
- [x] **One certification mechanism, not two (ADR 0031 — #218, #219).** docx 1.1.1, 2.4.4 and
  3.1.2 moved off the legacy `store.RULE_FORMATS` + `_certify` path onto the capability registry's
  coverage gate, verdict-for-verdict unchanged — ending the "two tables that agree by coincidence"
  hazard the registry exists to close. ADR 0031 records why coverage, not confidence, gates a
  certified pass (#218).
- [x] **docx lanes that existed in code but not in the index, declared (#202, #203, #206, #208)**
  and **three detectors that were silently Word-only, fixed (#205).** 1.4.1 and 1.4.11 got the
  guided cards that make both lanes assisted; 2.1.2 was the last Core-17 criterion with no `.docx`
  lane; 4.1.2 was already remediated deterministically and only lacked the declaration.
- [x] **Phase 5 — silent under-reporting closed (#214, #215, #216).** Link purpose is now judged
  in headers, footers and notes rather than the body alone (#214); tracked deletions no longer
  leak into extracted text (#215); the v2 capability table is synced to the backend and guarded so
  it stays synced (#216). Each was measured with a red fixture first. P5.3/P5.4 remain blocked on
  installs (LibreOffice, a mutation runner), not on design.
- [x] **Security & privacy (#209, #210, #213).** A non-owner could be redirected to another user's
  remediated document (#209); a reviewer's note left as text rather than a length (#210); a
  filename that names a patient now travels as a label, not the name (#213).
- [x] **Assessment honesty and the corpus gate (#204, #207).** The report now says what ACP
  checked, changed and verified — it does not certify (#204); the labelled corpus samples each
  criterion's boundary densely and bounds it by its own n (#207).
- [x] **v2 scan setup leads with a profile (#212)** — Step 1 now drives Step 2.

### Still open after today

The **production approval gate** (I.2 below) is the one that bit again: the auto-triggered deploy
waits on the `production` environment, and the UI approval has failed silently before. Until #223
merges the app stays in Multiple revision mode, so the next approved deploy will still strand its
new revision at 0% traffic — **merge #223 before approving any deploy.**

---

## Closed on 2026-08-08 — 14 PRs, 4 deploys, live at `2026.8.8.5`

- [x] v2 is the deployed app (#191) and the scope editor is reachable after a scan (#192)
- [x] File-type filter reaches Discover (#195) and every other tab (#196); `.docx` is the default
- [x] A scan cannot run on a scope that failed to save (#187)
- [x] `pdfjs-dist` 6.2.108 — arbitrary JS execution from a malicious PDF (#194)
- [x] OCR binary absence is announced instead of silently downgrading fixes to proposals (#190)
- [x] `num_predict` 60 → 400: reasoning models are no longer silenced (#198)
- [x] Backend CI 118s → ~60s (#189); corpus oracle regenerated (#188); capability report (#186)

### Verified current, needs no action

The **WCAG matrix is up to date.** All three repo-side guards pass (`gen_matrix_coverage`,
`gen_todo_status`, `gen_progress_log`), and the sister-repo dispatch correctly reported
`capability sources touched: no` — today's work changed UI, CI, dependencies and a token budget,
none of which alters what ACP can assess or remediate. The matrix has nothing new to publish
*because* no capability moved. Re-check with `gen_matrix_coverage.py --check` after any change
under `RULE_PATHS`.
