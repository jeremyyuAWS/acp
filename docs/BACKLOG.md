# ACP — gap closure backlog

Every item below is a gap **observed** on 2026-08-08, not a speculative improvement. Each names
the evidence, so anyone can re-check it rather than trust this file.

Context: the customer is a **hospital**, the documents are **PHI**, and the near-term scope is
**.docx only**. Those three facts set the priority order more than anything else here.

**Status key:** `[ ]` open · `[~]` in progress · `[x]` done · `[?]` needs a decision, not code

---

## Phase 0 — tonight (target: done by tomorrow morning)

Three items. The first two are investigations that could change what you tell the customer; the
third is the correctness fix with the widest blast radius.

- [ ] **P0.1 — Is `owner` derived from the session or the request?**
  `download_remediated(owner, scan_id, filename)` streams remediated files (`routes/scans.py:766,
  833`). If `owner` can come from a request parameter anywhere, that is a direct IDOR on patient
  documents. Everything else in this file is defence in depth; this one is exposure.
  *Effort: ~1h. Outcome: a yes/no you can put in writing.*

- [ ] **P0.2 — What does Langfuse capture in production?**
  Tracing records prompts by default, and ACP's prompts carry document text and OCR output. If
  tracing is on with PHI flowing through it, that is a second copy of patient data in a third
  party, and a BAA question. Check what is sent, and whether it can be disabled per-field.
  *Effort: ~1h.*

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
  **Still open from the proposal's "consequences" section, all three decisions rather than code:**
  scan diffs across differing scopes (ADR 0009), incremental-cache invalidation on a scope change
  (ADR 0011), and naming the unread formats in the PDF report's `_scope_section`.

---

## Phase 1 — before Monday

- [ ] **P1.1 — Walk v2 on a cleared browser.** `.docx` ticked by default; Discover filtered;
  Assess/Remediate/Overview agreeing. Everything verified so far has been static (bundle
  contents, minified strings, traffic weights). localStorage must be cleared first or the old
  config masks the change.
- [ ] **P1.2 — Rehearse the DOCX numbers.** 15 of 17 criteria have a docx lane · **4 can certify
  a PASS** (1.3.1, 1.4.3, 2.4.2, 3.1.1) · 9 fixes apply across 7 criteria · **3 are not assessed
  at all** (1.4.1, 1.4.11, 2.1.2). Source: `docs/capability-report.md`.
- [ ] **P1.3 — Say the Ontology gap out loud.** Custom labels and hierarchical taxonomy have no
  v2 equivalent (`Ontology.jsx` is v1-only; `ontology.js` data layer survives). Decide whether to
  port, defer, or drop before someone reaches for it in the room.
- [?] **P1.4 — Vision default.** `moondream` scores **0/6 facts and asserts a false year** on a
  real notice (`docs/local-model-evaluation.md`). `qwen2.5vl:7b` scores 3/6 at 4.4s. Blocked on
  the 8 GiB Consumption ceiling that forced moondream — ADR 0022 requires the CPU floor stay
  available, so this is an infrastructure decision, not a config change.

---

## Phase 2 — next week

- [ ] **P2.1 — Corpus ground truth: 5 → 61 pairs.** `config/rule-catalog.json` maps only DOCX
  rules to criteria, so 11 of the 16 rule IDs in the regenerated manifest cannot be tied to an
  SC. Until this lands, **nothing measures whether any detector is correct** — every lane in the
  capability report is a claim the engine makes about itself. Highest-value item for a customer
  who will ask "how do you know?"
- [ ] **P2.2 — Reconcile the three scope editors.** `ScanSetup`, `FileTypeConfig` and `ScanScope`
  each write all of `scan_scope`; last touched wins. `ScanSetup.jsx`'s own header calls this the
  *"two filters"* backlog item and says it needs a decision about which surface is authoritative.
- [ ] **P2.3 — Document-type scoping.** Discover *groups* by classification (HR, Legal,
  public-facing, legal-hold) but a scan cannot be *scoped* by it. For a hospital, "assess only
  legal-hold" is a more natural ask than file type, and the ontology data already exists.
- [ ] **P2.4 — The three unassessed DOCX criteria.** 1.4.1, 1.4.11, 2.1.2 have no lane and return
  `NOT_EVALUATED`. Decide: build, or state plainly that ACP does not assess them.
- [ ] **P2.5 — The 14 pairs with no recorded remediation decision.** `mode_for()` defaults them to
  `human`, so behaviour is consistent; what is missing is the decision. Confirm each was intended.

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
- [ ] **P3.5 — `vite@8` / `esbuild` CVEs.** 1 moderate + 1 high, **dev-only** (never loaded by a
  user's browser). Breaking major across both SPAs — worth doing, not worth doing this week.

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

- [ ] **P4.7 — Reproducibility metadata on every recorded result.** (PRD §26.) Model, revision,
  quantisation, runtime, prompt version, fixture version, hardware, temperature, seed.
  `judge_drafts.py` already records its shuffle seed; nothing else records anything. Cheap now,
  impossible to backfill.

- [ ] **P4.8 — Reviewer hand-off payload.** (PRD §36, and the one item with value *independent*
  of every policy question above.) When ACP escalates, give the reviewer the SC, the object, the
  crop, the deterministic evidence, the model's interpretation, the reason for uncertainty and
  the proposed fix — so a human resolves the remaining ambiguity instead of repeating the whole
  assessment. Pairs with the requested per-file/per-rule progress line during assessment and
  remediation. **Not blocked on P4.0.**

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

## Infrastructure — parallel track

- [ ] **I.1 — Azure agent pool.** Blocked on an admin granting it. All 14 merges on 2026-08-08
  bypassed Azure because 16 jobs were stuck behind the org's single parallel slot. Draft email
  written; agent built and merged (#183).
- [ ] **I.2 — Fix the production approval gate.** The UI approval silently failed three times
  today; the API worked instantly every time. Worth understanding before it blocks a release
  nobody can approve.
- [ ] **I.3 — Raise `num_predict` for 32B.** 400 fixed `qwen3:14b` and still truncates
  `qwen3:32b` (2 of 4 drafts empty). Only matters if a reasoning model is ever deployed.

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
