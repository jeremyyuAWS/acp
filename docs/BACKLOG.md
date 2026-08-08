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

- [ ] **P0.3 — Make the file-type filter reach the scanner.**
  Full scope in `docs/scope-reaches-the-scanner.md`. `scan_scope` gates criteria, never file
  reads: `routes/scans.py` has zero references to it, and enumeration is extension-only
  (`scanner.py:512`, `:876`). A `.docx` scan still downloads, OCRs and caches every PDF.
  Simultaneously a correctness fix, a data-minimisation fix, and a speed win — the only item that
  is all three.
  *Effort: 2–3h. Watch the HTML exemption and the `skipped_out_of_scope` counter.*

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
