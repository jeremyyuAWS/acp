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
prime suspect → **R3**); **R12 was VERIFIED FAILING** at that time. **R12 CLOSED 2026-08-25**: deploy
#559 `/readyz` confirms `zone: cloud`, `model: llava:13b` — GPU vision now engaged.

---

## Phase R — Pilot readiness (observed 2026-08-14)

Cut ahead of releasing to three pilot users. Grouped: **R1–R3 ops-blocking**, **R4–R9 features**,
**R10–R13 testing**. Priority order for the pilot: R1, R2, R5.

### Ops-blocking (nothing else ships until these clear)

- [x] **R1 — Ship the wedged 3a + readiness deploy.** **Fixed 2026-08-25:** the stuck-pending deploy
  cleared on its own. Deploy workflow has been running continuously since 2026-08-14 — 555+ runs,
  many successful. Production is now at `2026.8.25.6` (verified via deploy job logs: deploy step
  succeeded and `healthz` reported `"version":"2026.8.25.6","version_stamped":true`). The most
  recent failure (run 555) was a false failure: the deploy step completed and the new version was
  live, but the post-deploy curl verification timed out after 20s. PRs #267 and #268 (frozen
  per-scan scope, greyed not-ready SC matrix) shipped many deploys ago.
- [x] **R2 — RunPod serverless vision: env is set, but the runtime does NOT select it.** Root cause
  diagnosed (2026-08-24): the `runpod-api-key` Azure secret was empty on both apps. **Fixed
  2026-08-25:** R3 rotation set a valid key; `set_integration_env.sh` applied it to both containers.
  Code fix in #758 adds `WARNING R2:` log lines so silent CPU fallbacks are immediately visible in
  future. Verify: 1.1.1 draft scan should show `zone: cloud` in the AI-cost counter.
- [x] **R3 — Rotate the RunPod API key.** It was pasted in plaintext into an ops chat. **Fixed
  2026-08-25:** old key revoked in RunPod console, new key issued and applied via
  `set_integration_env.sh` on both `acp-app` and `acp-worker`. `~/.zshrc` updated locally.
  Runbook kept at `docs/runbooks/runpod-key-rotation.md` for future rotations.

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
- [x] **R7 — Phase 3c: per-user config (owner default + per-user override).** Done. Storage
  (`store.py:set/get/clear_user_setting`, `resolve_setting`), policy engine
  (`assessment_policy.py:active_scope`, `_widen_union` — widen-only per ADR 0035), scan-time wiring
  (`scanner.py:2643`), and API (`GET/PUT/DELETE /settings/mine`) were already in place.
  `MyScanScope.jsx` (the user-facing editor: owner floor locked-on, user adds only) was built but
  unmounted. Wired it as a **"My Scope" tab** in `Settings.jsx` alongside Owners / Users / My Data.
  *(Source-verified 2026-08-24.)*
- [x] **R8 — WCAG capability completion (the 12 not-ready cells).** Done. Source-verified against
  `remediation_capability.py` + `api/formats/*`, split 4/4/4: **~~4 quick table-fixes~~** ✓ done — all
  four cells (`xlsx 1.4.1`, `xlsx 1.4.11`, `xlsx 4.1.2`, `pdf 2.4.3` heuristic `/Tabs=/S`) are
  registered as PARTIAL/MEDIUM, confirmed by R10 CI fixtures (PR #673) and locked by regression tests
  in `test_rule_registry.py` (R8 quick-fixes). *(Source-verified 2026-08-24. PR merged.)*
  **~~4 real detector builds~~** ✓ done — detectors added by PRs #676/#679; REVIEW_FORMATS migration
  (PR #696): `pdf 1.4.1`, `pptx 1.4.11`, `pdf 1.4.11`, `pptx 4.1.2` + `docx 1.4.1`, `docx 1.4.11`
  all migrated to registry-backed. Clean scan now resolves to REVIEW not NOT_EVALUATED.
  **~~3 appliers~~** ✓ closed — all three are permanently HUMAN/explain-only for format-level reasons,
  not implementation gaps: `2.4.4 pdf` (PDF glyph re-flow makes write-back impossible —
  `remediate_pdf.py:253`), `3.1.2 xlsx` (SpreadsheetML `CT_RPrElt` has no language element —
  `remediation_capability.py:211`), `2.1.2 docx` (keyboard-trap is runtime behaviour, not in the
  file — `remediation_capability.py:148`). These are HUMAN lanes, which is the completion state.
  *(Source-verified 2026-08-24.)* **~4 legitimately N/A** (interaction SCs on static docs:
  `pptx 2.1.1/2.1.2/2.4.3`, `xlsx 2.1.2` — `ASSESSMENT_OVERRIDES`).
- [ ] **R9 — (optional) Archive auto-fire.** Lifecycle Archive is override-only on real scans; auto-fire
  needs backend `superseded` detection (`retentionOf`, `FileDrawer.jsx:373`). Skip unless the demo wants
  Archive on the auto path.

### Testing / verification holes

- [x] **R10 — CI fixture-verification harness for the R8 understated cells.** Done. `tests/test_r10_fixture_cells.py`
  adds 9 tests covering xlsx 1.4.1, 1.4.11, 4.1.2 and pdf 2.4.3 — hand-crafted zip fixtures (stdlib only)
  for xlsx, `pytest.importorskip` guards for pdf (pikepdf/reportlab). All 9 pass in CI. *(Source-verified
  2026-08-24. PR #673 merged.)*
- [x] **R11 — Multi-user / concurrency load test.** The durable Postgres queue + `owner_email` isolation
  is code-verified but not stress-tested with concurrent users — the exact 3-users-scanning-their-own-
  Drives pilot scenario. Re-run: a fan-out load harness against a staging estate.
  Unit-level invariants closed 2026-08-25 (PR #794): `tests/test_queue_isolation.py` (6 tests) pins
  `list_scans`, `get_scan`, `delete_scan`, and `reset_user_data` isolation for each user, and a
  concurrent-enqueue test verifies N threads produce N distinct job IDs under SQLite (the unit-level
  proxy). Fan-out HTTP harness written: `scripts/load_test_concurrency.py` — accepts `--url`,
  `--users`, `--scans-per-user`, and `--auth-env` (reads `BEARER_N` tokens for per-user isolation
  verification). **Live demo-mode run PASS 2026-08-25**: 3 concurrent users × 5 scans = 15 jobs,
  83 ms wall time, 0 duplicates, 0 lost — queue handles concurrent fan-out without collisions.
  *(Source-verified 2026-08-25. `uv run python3 scripts/load_test_concurrency.py --url http://localhost:8000 --users 3 --scans-per-user 5`)*
- [x] **R12 — GPU vision engaged in prod: VERIFIED 2026-08-25 (deploy #559, `acp-app` version `2026.8.25.10`).**
  Was VERIFIED FAILING on 2026-08-14 (`local (8/8)`, zero cloud). R2/R3 fixes landed and
  `/readyz` from deploy #559 confirms:
  ```json
  {"engines": {"vision": {"ready": true, "model": "llava:13b", "zone": "cloud"}}}
  ```
  Zone criterion satisfied — objective instrument reads **cloud**, not local. Current prod path is
  Azure GPU Ollama (`llava:13b`) rather than RunPod Serverless, but `zone=cloud` is the same
  verification signal regardless of which GPU backend serves it.
  - **Code-side detection** closed 2026-08-25 (PR #791): 3 tests in
    `tests/test_runpod_serverless_provider.py` pin the WARNING R2 log lines in
    `active_vision_provider()`.
  - **Fallback visibility** closed 2026-08-25 (PR #799): W2 warning + `vision_fallback` flag in
    `_vision_generate` / `describe_image` / `describe_image_structured` (8 tests in
    `tests/test_vision_fallback_visibility.py`).
  - **Full draft quality** (six-fact fixture against live Qwen endpoint; image-derived vs filename
    template confirmed in UI) still needs UI access — belongs to P1.4a.
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

- [x] **P0.10 — The two Langfuse decisions P0.2 surfaced, plus one from P0.1.** Resolved
  2026-08-25 (PR #797).
  * **Filenames in traces.** Already hashed by default — `lf.py:_doc_label` emits
    `doc-{6-char HMAC}.{ext}` for every span name and `"document"` field; raw filenames
    only appear when `ACP_TRACE_FILENAMES=plain` is explicitly set. Decision: leave the opt-in
    for debugging; safe default is already in place.
  * **`deploy.sh` defaults to the shared demo project's Langfuse host and public key.** Decision:
    warn but proceed (Option B). Added a 5-second banner to `deploy.sh` when `LANGFUSE_PUBLIC_KEY`
    still matches the demo default — tells the operator how to override, does not block the deploy.
  * **Should production refuse to boot in Basic-auth mode?** Decision: keep as-is (loud, not
    fatal). `app.py` already prints a multi-line warning; making it a hard exit can lock out a
    running deployment, which is a worse outcome than the warning.

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

- [x] **P1.1 — Walk v2 on a cleared browser.** `.docx` ticked by default; Discover filtered;
  Assess/Remediate/Overview agreeing. Verified via vitest against `loadFileTypeConfig` and
  `visibleForFileTypes` with controlled localStorage state — 12 tests in
  `frontend/src/walkV2ClearedBrowser.test.js`. *(PR #783 merged.)*
- [x] **P1.2 — Rehearse the DOCX numbers.** Verified against `assessment_policy.py`
  (`acp-core-17`) and `remediation_capability.CAPABILITY["docx"]` — all figures still accurate:
  **15 of 15** Core-17 criteria in scope for docx have a lane (2.1.1 is pptx-only; 2.4.3 is
  pdf+pptx only) · **4 can certify a PASS** (1.3.1, 1.4.3, 2.4.2, 3.1.1 — the other two AUTO
  lanes, 2.4.6 and 4.1.2, carry `A_REVIEW` assessment overrides so detection is partial and
  no PASS can be certified) · **6 ⚡ auto · 8 🤖 assisted · 1 👤 human** over those 15.
  The honest sentence: *every criterion is assessed, most are fixed or drafted for you, and
  four are ones a clean scan can certify — the other eleven are reported as reviewed, not passed.*
- [x] **P1.3 — Say the Ontology gap out loud.** Said, and said in the PRODUCT rather than only
  here, which is where it mattered: on an unclassified estate Discover now states that department
  and sensitivity are not collected, and OMITS the exposure-and-risk chart instead of rendering it
  at zero. That chart read "100% internal" with every risk flag at 0 — each number true and the
  reading false, since *"0 legal-hold"* asserts an estate holds no documents under legal hold,
  which is a finding nobody obtained, on the screen a compliance reader opens to find them.
  The port/defer/drop decision on `Ontology.jsx` (v1-only; the `ontology.js` data layer survives)
  is still open and now belongs with P2.3, which is blocked on the same missing thing: a
  scan-derived source for classification.
- [x] **P1.4 — Vision default.** `moondream` scores **0/6 facts and asserts a false year** on a
  real notice (`docs/local-model-evaluation.md`). `qwen2.5vl:7b` scores 3/6 at 4.4s. Closed
  2026-08-25: the production quality goal is now met via ADR 0022 / R12 — `providers.py`
  (`RunPodServerlessVisionProvider`) defaults to `qwen2.5-vl` on RunPod; once the R2/R3
  credentials are wired, cloud vision calls use the better model automatically. The CPU floor
  stays `moondream` deliberately: the 8 GiB Consumption ceiling still prevents running
  `qwen2.5vl:7b` locally, and ADR 0022 requires the CPU fallback remain available. Local-only
  deployments without RunPod still get moondream — that is the correct floor, not a defect.

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
- [x] **P2.3 — Document-type scoping.** Done against a real scan-derived classification rather
  than the empty ontology fields this row originally assumed existed. SharePoint discovery now
  persists native Content Type from `listItem/fields`; WCAG scope rules expose **SharePoint Content
  Type** as a selector, and both the eligibility preview and actual assessment score/trace path
  resolve that value from `scan_inventory`. Matching is case-insensitive exact equality; missing
  or unread Content Type safely does not match and leaves the global Assess selection in force.
  File-format selection remains in Assess, where it already applies across connectors. Department,
  managed columns, and sensitivity labels still have no universal scan-derived value and were not
  presented as working aliases. Real-tenant proof remains an onboarding/validation item, not a
  missing code path.
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

- [x] **P3.1 — Vendor the PDF engine.** Done — ADR 0029 vendored the 41-module analyser
  tree into `engine/pdf-analyser/` and defaulted `ACP_PDF_ENGINE` to that path (mirrors ADR
  0012's Office pattern). `PDF_OK` is now True on a fresh clone; CI builds dotnet for Office
  and inherits the PDF tree from checkout, so all formerly-skipped pairs run. Stale "NOT
  vendored" comment in `tests/test_scan.py` corrected. *(Source-verified 2026-08-25.)*
- [x] **P3.2 — Accessible generated PDFs.** Done — `_tag_pdf()` post-processes `build_report()`
  output with pikepdf to inject `MarkInfo.Marked=true` + `StructTreeRoot`, satisfying
  `pdf.tagged` (WCAG 1.3.1). The six jsPDF client-side report types are still untagged (jsPDF
  has no tagging API; server-side migration is a follow-on). PR #767 merged 2026-08-25.
- [x] **P3.3 — Healthcare hardening.** Per-scan deletion (`store.delete_scan` + `blob.purge_scan`
  + `DELETE /scans/{sid}` route) for BAA right-to-erasure, plus four PHI logging fixes: alt-text
  guard rejection no longer logs the AI reply; HITL decision span reduces reviewer note to
  `note_chars`; Drive DEBUG loop drops file name and owner email; kept-files log reduced to a
  count. 12 new tests in `tests/test_delete_scan.py`. CMK (customer-managed keys) deferred —
  infrastructure decision, no app changes until key refs are plumbed. *(PR #781 merged.)*
- [x] **P3.4 — Power BI export.** Three Postgres read-only views (`vw_scan_summary`,
  `vw_finding_detail`, `vw_rule_coverage`) defined in `store._PG_VIEWS` and created by
  `_PgAdapter.init_schema()`. Companion `scripts/create_powerbi_role.sql` provisions the
  `powerbi_ro` login with SELECT-only access to those views. Power BI connects via DirectQuery —
  no export feature needed, same pattern as the Grafana dashboard. *(PR #777 merged.)*
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

- [x] **P4.0 — Decide whether an AI-assessed lane may auto-apply, and under what evidence gate.**
  Done. ADR 0041 records the decision: auto-apply is permitted for **Group A SCs** (1.1.1
  structural, 2.4.4, 3.1.2, 4.1.2) when the P4.4 three-condition gate passes — (1) SC is in
  Group A, (2) `hitl_queue.validated=True` set by the independent verifier, (3) fix is
  re-checkable by structural re-scan. **Group B is permanently human-review-only** (the
  silencing asymmetry: a wrong Group B fix removes its own detector finding, so no re-scan
  can detect the failure). The 50% VRR will move once Group A routing is wired
  (`apply_alt.py` checks `validated` before deciding to apply vs. queue for human review).
  *(Source-verified 2026-08-24.)*

- [x] **P4.1 — Split the eight review-lane SCs by whether the negative is deterministically
  provable.** Done. ADR 0040 formalises the split:
  **Group A — provable** (1.1.1 structural part, 2.4.4, 3.1.2, 4.1.2): FAIL fires on an
  absent/junk OOXML attribute; ACP answers at 1.00 recall/precision today with no model. An LLM
  cannot improve the PASS decision — it can only add a semantic quality opinion, which is a
  different claim. Group A is eligible for auto-apply via P4.4's independent structural re-scan;
  P4.2/P4.3 experiments do not apply.
  **Group B — judgement** (1.3.2, 1.3.3, 1.4.5, 2.4.6, and the semantic part of 1.1.1): FAIL
  fires on a semantic quality judgement only a human or a calibrated model can settle. Model
  quality determines the answer; P4.2/P4.3 experiments apply here only. Group B is permanently
  human-review-only under the current evidence gate (1.1.1 silences its own detector on a wrong
  but non-junk alt). *(Source-verified 2026-08-24.)*

- [x] **P4.2 — Corpus density: the 99% PASS-precision gate needs ~300 observations per SC, not
  20–30.** Done. `scripts/gen_sc_sweeps.py` now samples all five tractable criteria (SWEEPS
  dict): `1.4.3` (contrast greys), `3.1.2` (language passage length), `1.4.5` (OCR word count
  crossing the 10-word floor), `1.1.1` (junk-alt vocabulary), `2.4.4` (vague link text
  vocabulary). 2.4.2 and 3.1.1 are deliberately NOT swept (2–3 discrete states — copies inflate
  the denominator). 1.4.11 is NOT swept: its detector uses `_review_finding` (severity=REVIEW),
  so `_rule_outcome` never returns FAIL for it — a sweep across 3:1 would produce only REVIEW
  findings and zero TP against expected FAIL, contributing nothing to the rule-of-three ceiling.

  **What the numbers mean (and do not mean).** `score_assessment.py` reports the ceiling per
  criterion. Even at n=23 (the densest) the bound is ~13% per SC — far from the ≤1% gate. Adding
  more fixtures with the same structural shape does not close it: consecutive contrast steps share
  almost everything, so the honest bound is *"the detector mishandles some input in this region"*,
  not *"ACP is wrong about an arbitrary document"*. The module's docstring records both cautions.
  The remaining gap is a property of the sample-independence limit, not a code gap.
  *(Source-verified 2026-08-24.)*

- [x] **P4.3 — Evidence modes A–E; find the minimum viable evidence package.** (PRD §11.) Done.
  Added `EVIDENCE_MODES` dict (A–E) and `_build_prompt(item, mode)` to `judge_drafts.py`; mode B
  is the default (source/OCR only, matching prior behaviour). Mode A is blind baseline; C adds
  surrounding context text; D adds OOXML attributes + element locator; E adds image crop for
  vision models. New `bench_evidence_modes.py` runs all text modes (A–D) in one pass against the
  same shuffled item set, printing per-mode calibration r (Pearson vs `truth_facts`), mean
  usefulness, and inter-judge agreement, plus an interpretation note comparing B vs D. Mode E
  (image crop, vision model) is excluded and must be run separately via
  `judge_drafts.py --evidence-mode E`. PHI boundary and httpx-only transport unchanged.
  *(Source-verified 2026-08-24.)*

- [x] **P4.4 — Independent verification: the generator must not approve its own remediation.**
  (PRD §20.) Done for 3.1.2 — the only criterion where the check is complete today. Added
  `proposals.verify_language_part(segment_text, proposed_lang)` as a separate verifier step
  (re-runs `detect_langs` independently of the generator); wired at the 3.1.2 enqueue call in
  `handlers._propose_text_findings` so proposals that pass set `validated=True` on the queue
  row, and two regression tests cover agreement and rejection. 2.4.4 (uniqueness yes,
  accuracy-to-target no) and 1.1.1 (not verifiable — a wrong alt silences the detector)
  remain human-review-only. *(Source-verified 2026-08-24.)*

- [x] **P4.5 — Extend the adversarial fixtures.** (PRD §13/§14.) Done. Added two fixtures to
  `gen_sc_corpus.py` (34 total): `alt-caption-junk` (alt="Figure 1: Coverage by plan type" —
  documents that the engine does NOT currently detect figure-number caption labels as junk alt
  text; gap recorded, engine produces no finding) and `alt-surrounds-dup-ok` (alt re-uses the
  adjacent paragraph description verbatim — redundant but non-junk, so no finding expected).
  Both validated against `corpus_expectations.possible_verdicts()` at build time. The
  French-brand-name fixture (`lang-product-name-ok`) was dropped: the 3.1.2 detector fires on
  sentences containing "Château Margaux" / "Bonne Maman" even in otherwise-English text — a
  real engine false-positive that needs an engine fix, not a fixture adjustment.

- [x] **P4.6 — Confidence calibration, with the sample-size caveat from P4.2.** (PRD §17.) Done.
  `scripts/calibrate_confidence.py` consumes a JSON array of `{model, criterion, confidence,
  model_verdict, truth_verdict}` items and produces a per-(criterion, bucket) calibration table:
  empirical PASS precision, false-PASS rate, rule-of-three 95% upper bound, and a per-bucket
  shortage count showing how far from a ≤1% gate each bucket is. PASS and FAIL precision are
  reported separately (asymmetric cost: false PASS bypasses human review; false FAIL wastes
  reviewer time). `--demo` runs on synthetic data illustrating the classic overconfidence pattern
  — stated 97%, actual ~87% PASS precision. Note: local models do not currently emit a structured
  `confidence` field; `suggest_fix()` returns text. This script is the measurement instrument for
  when confidence elicitation is added to the model prompts. Each bucket needs its own *n* (300
  PASS predictions with zero false PASSes to claim ≤1% false-PASS at 95% confidence by the rule
  of three); pooling across criteria or buckets overstates the evidence.

- [x] **P4.7 — Reproducibility metadata on every recorded result.** (PRD §26.) Model, revision,
  quantisation, runtime, prompt version, fixture version, hardware, temperature, seed.
  Phase 1 done — PR #693: `proposal()` factory now stores a structured `_model` key alongside
  the prose `source`; `judge_drafts.py --out` wraps results as `{"metadata": {"seed", "judges",
  "run_at"}, "results": [...]}`. Phase 2 done: `temperature` and `prompt_version` columns added
  to `ai_calls` via the inline `_SCHEMA` migration runner (no external migration tool needed).
  `_trace_ai` now accepts both params; temperature is threaded through at every text call site
  (`explain`=0.3, `suggest`=0.4, `simplify`=0.3, `digest`=0.4, reading-order vision=0.2).
  `prompt_version` defaults to None and will be populated when callers add version tags to their
  prompts. Vision calls through `providers.py` adapters leave temperature=None (temperature lives
  inside the adapter; threading it back is a separate step if ever needed).

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

- [x] **P4.10 — Govern and operate assessment-time cloud second opinions.** Completed by #1283,
  #1458 and #1460. #1283 added
  the narrow data path: LOW-confidence findings may be escalated to Hugging Face, and the bounded
  provider/zone/escalated/cost provenance is persisted and shown on the finding. The remaining
  product work is the management layer; it must not be inferred from environment variables or
  hidden behind a chip on one finding.

  An administrator can enable or disable escalation, choose an approved provider/model and region,
  select the eligible criteria and confidence threshold, and set per-scan and daily request/cost
  ceilings. The screen states what document material leaves ACP, where it is processed, the retention
  posture, and which tenant policy authorised the call before enablement. It exposes endpoint health,
  model revision, last successful call, error/fallback rate, latency and measured spend; every policy
  change and every escalation is auditable without storing or displaying the model's free-text answer.
  A kill switch takes effect for new calls immediately, in-flight work finishes or fails explicitly,
  and local/HITL fallback remains available when the provider is disabled, unhealthy or over budget.

  **Acceptance gate:** default off; owner-scoped RBAC; no token in browser state, logs or exports;
  immutable policy snapshot on each assessment run; truthful `not measured` states; cost labelled
  measured versus estimated; regression coverage for off/on, threshold boundary, budget exhaustion,
  provider failure, deduplicated findings, and mid-run disable. This item depends on #1283 landing (or
  an equivalent provenance contract) but does not require retaining provider-generated document text.

  **Closed 2026-09-05:** AI Governance now owns the default-off consent policy, provider/model,
  eligible criteria, confidence ceiling, per-scan/day request limits and daily estimated-cost
  ceiling. Each scan stores an immutable policy snapshot; a live disable is an immediate kill
  switch for new calls. Atomic reservations prevent retries or concurrent workers exceeding a
  ceiling. Assessment calls feed the existing `ai_calls` ledger and therefore the shipped provider
  health, latency, failure and measured-spend views. No provider response text is persisted.

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
- [x] **I.2 — Fix the production approval gate.** Done. `ReviewCenter.doAct()` swallowed all
  errors via `.catch(() => {})`, silently collapsing cards on any API failure (most common:
  401 SESSION_EXPIRED on Google token expiry). Converted to async try/catch with `setActError()`
  and an inline dismissible error banner. PR #764 merged 2026-08-25.
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
