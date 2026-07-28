# ACP — comprehensive to-do

Authored sections reviewed against `d289a63` (main, 2026-07-28). The previous
snapshot was `9d7c7a3` — **387 commits and 19 days earlier**, and several items
below had shipped without being struck through. That is the failure this file's
new split is meant to prevent:

* **Generated** — the coverage-status block below is derived from the code that
  decides it, and `scripts/gen_todo_status.py --check` fails CI when it drifts.
  Nothing forced the old counts to stay current, so they didn't.
* **Authored** — everything else. Whether we build a thing, when, who owns it,
  and why it was deferred are judgements no generator should fake.

Items are struck through when the code says they shipped, with the evidence
named — not when someone remembers closing them.

Current coverage (87 WCAG 2.1/2.2 success criteria) — **authored, and NOT
re-verified in this pass.** These counts are derived from
`frontend/src/wcagCatalog.js`, which is not present in this checkout, so they
carry the same staleness risk the rest of this header just shed. Treat them as
2026-07-09 figures until someone re-counts against the catalog. The generated
block further down is the part that is guaranteed current.

| Bucket | Count | Meaning |
|---|---|---|
| Shipped (demo) | 36 | Real automated validator, verified backing |
| MDK HITL | 45 | Human-judgment criteria (captions, timing, error text, media, gesture alternatives) — routed to the HITL queue |
| Partner baseline | 6 | Covered by the .NET partner engine (`spike/dotnet/AcpScan.Cli`) |
| ~~Roadmap~~ | 0 | **CLOSED (`75fc6b8`)** — the 5 pure-media AAA "MDK net-new" SCs (1.2.6/1.2.7/1.2.8/1.2.9/1.4.7) were already `Human / AT` + Tier 3, so they already rendered HUMAN-tier per file; reclassified `net-new → MDK HITL`. Zero roadmap. |

Every one of the 87 SCs now has a closed disposition: Auto-detected (36),
HITL (45), or Partner (6). **No Required (A/AA) gap** — every Required
criterion is auto-detected or HITL-routed matching the checklist's own
"Human / AT" designation.

**The 4 Required format gaps (1.4.1, 1.3.5, 2.5.3, 4.1.2)** were this file's
headline open item for months, described as "auto-detected for HTML but
UNCHECKED for PDF/Office". Two thirds of that is no longer true, and the
generated table below now answers it with live data every run instead of a
sentence nobody re-checked.

The distinction it asked for — *"doc-applicable, not-auto-here"* versus
*"web-only → N-A"* — is exactly what `Coverage.DECLARED` and
`Coverage.UNSUPPORTED` encode in `api/rule_registry.py`, arrived at from the
other direction while fixing 4.1.2 on PDF. `1.4.1` and `4.1.2` now carry real
per-format signal; `1.3.5` and `2.5.3` remain HTML-only and are the genuine
remainder.

<!-- BEGIN GENERATED: coverage-status — written by scripts/gen_todo_status.py. Do not
     hand-edit: the next run overwrites it, and `--check` fails CI if it is stale. -->

### Coverage status — generated, do not edit by hand

Regenerate with `python scripts/gen_todo_status.py`; CI fails if this block is stale (`--check`). Everything below is read from `api/rule_registry.py`, `api/store.py` (`RULE_FORMATS` / `REVIEW_FORMATS`) and `config/rule-catalog.json` — the code that actually decides it. Intent, priority and ownership are authored above and below; this block never speaks to those.

**Conformance target: AA.** Criteria above the target are not assessed at all (`store.in_target`). Selectable targets are A, AA, so the 7 AAA criteria are never assessed: `1.4.6`, `1.4.8`, `1.4.9`, `2.4.10`, `2.4.9`, `3.1.4`, `3.1.5`.

This is a behaviour change, not bookkeeping: several detectors compute the AA and AAA thresholds in one pass, so AAA findings were previously scored against AA-target files.

**Capability registry — 4 (criterion, format) pair(s) migrated.** Coverage is declared beside the detector; only `full` may certify a pass.

| Criterion | Format | Coverage | Confidence | Not covered |
|---|---|---|---|---|
| `1.4.11` | xlsx | **partial** | medium | theme-coloured shapes, gradients, images and control affordances are not examined, and whether a shape conveys |
| `2.4.3` | pdf | **heuristic** | medium | actually comparing the widget order to the structure order needs a /StructTreeRoot walk that is not built |
| `3.1.1` | html | **full** | high | whether the declared language is the CORRECT one is a content question 3.1.1 does not ask |
| `4.1.2` | pdf | **partial** | high | components expressed through the tagged-structure tree are not examined, which needs a /StructTreeRoot walker  |

**The four Required format gaps** this file's header has tracked since the first snapshot — auto-detected for HTML, historically UNCHECKED for PDF/Office:

| Criterion | HTML | DOCX | XLSX | PPTX | PDF |
|---|---|---|---|---|---|
| `1.4.1` | pass/fail | review | review | — | review |
| `1.3.5` | pass/fail | — | — | — | — |
| `2.5.3` | pass/fail | — | — | — | — |
| `4.1.2` | pass/fail | review | review | review | partial |

`partial` / `heuristic` / `full` come from the registry and mean a real detector runs. `review` means a review-lane detector surfaces evidence but never certifies. `—` means no signal of any kind — the genuine remaining gap.

**Undeclared coverage** — detectors emitting for a (criterion, format) that no scope table admits. `scripts/gen_matrix_coverage.py` reports these; all known instances (`1.4.11` xlsx, `2.4.3` pdf, `4.1.2` pdf) are now declared in the registry.

<!-- END GENERATED: coverage-status -->

All of this session's new detection code (`office_structure.py` +
`textchecks.py`) went through an adversarial correctness review (`9d7c7a3`)
that found and fixed 9 real defects — most notably the xlsx-contrast check was
reading the wrong style block on essentially every real workbook, and the
reading-level check false-fired on punctuation-free extracted text. Both are
fixed with regression tests. See P1c.

No TODO/FIXME/XXX comments, no skipped tests, and no ADR left in Proposed/Draft
status anywhere in the repo — this file is the single backlog.

---

## P0 — Known bugs

None outstanding. The two correctness bugs found this session (duplicate
findings in FileDrawer, and the 10-SC false-PASS bug where several rules had
zero backend validator at all) are both fixed and committed (`92189ce`,
`db6326c`). If you hit something new, add it here before fixing it blind.

---

## P1 — Tier 2 format-coverage gaps (scoped out of the last pass, real work)

Three of four shipped (`22a7202`, `a916068`, `5ec86b6`); one is genuinely
blocked, not just deferred. Each landed with real fixtures verified before
implementing — no guessed detection logic.

1. ~~**PDF outline-tree analog for 2.4.1 (Bypass Blocks)**~~ — SHIPPED
   (`22a7202`). `pdf_bypass_blocks_check()` in `office_structure.py`, via
   pikepdf's `/Root/Outlines`. Only checked at 5+ pages (a short memo has no
   real bypass-blocks problem).
2. ~~**pptx embedded-audio autoplay (1.4.2 Audio Control)**~~ — SHIPPED, and
   this entry was stale for most of those 387 commits. `pptx_audio_autoplay_checks()`
   is in `office_structure.py`, dispatched from `checks_for()`'s `.pptx` branch,
   covered by `tests/test_office_structure_audio.py`, and carries an `assisted`
   remediation lane (`remediation_capability.REMEDIATION["pptx"]["1.4.2"]` — a
   one-click play-on-click card a human elects).

   The blocker recorded here was real when written: the `<p:timing>` trigger XML
   distinguishing autoplay from click-to-play could not be verified without a
   ground-truth fixture. It was resolved by reading the condition structurally —
   `<p:cond delay="0">` starts it, `evt="onClick"` does not — rather than by
   obtaining the fixture the entry was waiting on.
3. ~~**docx/pptx form-field labeling (3.3.2 / 4.1.2)**~~ — SHIPPED
   (`a916068`), docx only. `docx_checks()` flags content-control form fields
   (checkbox/date/dropdown/comboBox/picture — the unambiguous input gallery
   types) missing a `w:alias` title. Verified against 3 independent sources
   that `w:sdt` also wraps non-form content (TOC blocks, citations) that
   must NOT be flagged — pptx form controls were assessed as too rare to be
   worth a separate pass. Ships as 3.3.2 only, not 4.1.2 (4.1.2 is broader
   than just labeling and wasn't fully verified as covered).
4. ~~**xlsx contrast (1.4.3 / 1.4.6)**~~ — SHIPPED (`5ec86b6`), deliberately
   narrow. `xlsx_contrast_checks()` resolves cell font/fill color through
   `xl/styles.xml`'s cellXfs → fonts/fills chain, but ONLY direct
   `<color rgb="...">` — theme= and indexed= colors, and non-solid pattern
   fills, resolve to "unknown" and are skipped rather than guessed at (theme
   colors are exactly what Excel's built-in header/table styles use).
   Conditional-formatting (`cfRule`) overrides are out of scope entirely.

---

## P1b — AAA/optional assess gaps pulled out of HITL (`7eafe79`)

Deterministic detection for two document criteria that previously surfaced
only as manual-checklist (HITL) items — now auto-assessed, remediation still
human-only (both are inherently judgement calls to fix):

1. ~~**2.4.10 Section Headings**~~ — SHIPPED (`7eafe79`), docx.
   `docx_checks()` flags a body past a text-bearing-paragraph floor
   (`_MIN_PARAS_FOR_HEADINGS`) with zero heading styles. Short letters/memos
   below the floor are not flagged.
2. ~~**3.1.5 Reading Level**~~ — SHIPPED (`7eafe79`), all formats via
   `textchecks.py`. Flesch-Kincaid grade level over extracted text, flagged
   only well above the SC's grade-9 floor (mid-college+) so it stays
   actionable rather than firing on ordinary professional prose. No new deps
   (heuristic syllable count).

3. ~~**1.4.8 Visual Presentation**~~ — SHIPPED (`eb542d4`), docx. `docx_checks()`
   flags blocks of body text set justified (both margins), an explicit 1.4.8
   failure, past a `_MIN_JUSTIFIED_PARAS` floor. Narrow by design (justified
   alignment only, not the SC's full width/spacing/colour surface) — same
   honest-partial posture as xlsx-contrast and 3.3.2.

Remaining automatable AAA/optional candidate, not yet built (lowest value):
3.1.3 Unusual Words — needs Ollama-assisted glossary detection, i.e.
non-deterministic, which cuts against the compliance-tool principle that
identical input must give identical findings; left unbuilt on purpose.
Everything else doc-applicable is genuine human-judgment (correctly HITL) or
web-only (N/A).

The one deterministic *remediate*-side candidate worth considering: PDF
bookmark-outline auto-generation for 2.4.1 (we already *detect* the gap). NOTE
(revised): a *meaningful* outline needs to know what the headings ARE, which
for an untagged PDF means font-size/style heuristics — that's judgement-laden
and risks emitting garbage bookmarks. Not a clean deterministic fix; only worth
doing for already-tagged PDFs (rare). Left as a decision, with that caveat.

---

## P1c — Correctness hardening of this session's detection code (`9d7c7a3`)

An adversarial review of every new check found **9 real defects** (all
reproduced, all fixed with regression tests) before the code went live. The
two that mattered most:
- **xlsx contrast read the wrong style block.** A cell's `s="N"` indexes only
  `<cellXfs>`, but the regexes matched every `<xf>`/`<font>`/`<fill>` in
  styles.xml — including `<cellStyleXfs>` and the `<dxfs>` conditional-format
  differentials — shifting every index. It mis-read colour on essentially every
  real workbook. Now scoped to each real container block.
- **3.1.5 reading level false-fired on punctuation-free text.** Bulleted/table
  extraction with no terminal punctuation collapsed to one "sentence" and the
  FK grade exploded (a 3rd-grade bullet list scored 86). Newlines now count as
  sentence boundaries; unpunctuated blobs decline to score.
The other 7 (dedup-link false positive on shared URLs, PDF contrast 40-char cap
+ grayscale/CMYK colour handling, pptx title `idx=`/paired-tag forms, `<a:t>`
`xml:space`, docx regex whitespace) are all fixed too. This is the kind of bug
the honest-detection bar exists to catch — worth the review pass before any
unsupervised live window.

---

## LOE — remaining work to full functionality

Principle (owner's call): anything not auto-remediable by a deterministic or AI
fixer **routes to HITL** — so no new auto-fixers are required for the long tail;
non-mechanical findings already surface as HUMAN-tier and go to the review queue.
Route legend: **Auto** (deterministic/AI fix) · **HITL** (human review) · **Ops**
(credential/config) · **Decision**.

| # | Item | Verb | Route | LOE | Notes |
|---|---|---|---|---|---|
| 1 | Fix live "Couldn't remediate this file" | Remediate | Auto | M · 1–2 d | Runtime failure in the Drive round-trip (re-download via per-user token / write-back), NOT a remediator bug — `remediate_pdf` runs clean locally on the same file (applies language + display-title). Likely the write-back needs a Drive *write* scope the read-only sign-in token lacks, and the Blob fallback isn't catching it. Lives in `handlers.py` / `routes/scans.py` — **T-contested; coordinate**. |
| 2 | Complete the DB-backed HITL queue | Remediate | HITL | In progress (T) | Assignment, status, notifications — this IS the HITL route. Owned by the concurrent session (~M if scoped fresh). |
| 3 | 3.1.3 Unusual Words | Assess | HITL | ~~XS~~ DONE | Re-tagged Human / AT · Tier 3 HITL in `wcagCatalog.js` (was aspirational "Automated + Agentic"). No AI check built, by decision. |
| 4 | ~~1.4.2 pptx audio autoplay~~ | Assess | — | DONE | Detection shipped (`pptx_audio_autoplay_checks`, dispatched, tested) with an `assisted` remediation lane — no longer blocked on a fixture, and no longer HITL-only. See P1 #2. |
| 5 | Deploy the mislabel fix (`e83d775`) | Release | — | XS · 0.25 d | Frontend rebuild — makes corrected auto-vs-assisted labeling live. |
| 6 | Drive credential + folder | Ops | Ops | S · 0.5 d | Regenerate the demo SA key with `drive.readonly`, share Deva's folder with the SA email, set `ACP_DRIVE_FOLDER`. Unblocks demo Drive scans (the 403 below) and closes P2 #1. Ops, not eng. |
| 7 | Measure Ollama 8B latency | Verify | — | XS · 0.25 d | Needs live access; include a cold-start number (scale-to-zero). |
| 8 | ADO review cadence | — | Decision | 0 d | Standing reviewer vs. bypass-as-needed. |

**Real engineering build left ≈ 2–3.5 person-days, almost all of it item #1**
(and #1 is blocked on coordinating with T's rewrite of that exact code, not on
effort). Item #2 is T's. Items #4–7 are hours; #3 is done; #8 is a decision.

**Two mislabel/UX fixes already landed this session:** the "fully automatic"
misclassification (`e83d775`, `sim.js` — real-vs-sim wcag format mismatch +
format-aware auto set) and the 9 detection-code defects (`9d7c7a3`).

### Live Drive-flow finding (`403 insufficient scopes`)
A headless smoke test of `POST /scans?source=drive` (via the E2E + demo keys)
authenticated and reached Drive, then failed at `files.list` with Google
`403 "Request had insufficient authentication scopes"`. The code correctly
requests `drive.readonly` (`scanner.py` `SCOPES`), so the stored demo ADC
credential can't obtain that scope — a credential/config issue, not a code bug.
Fixed by item #6. (Real usage via signed-in users' own Drive tokens is
unaffected; only the demo/ADC path is broken.)

---

## P2 — Decisions pending on the user (not blocked on engineering)

1. **Point `ACP_DRIVE_FOLDER` at Deva's folder** for scheduled sweeps —
   waiting on the folder ID.
2. **Measure real Ollama `llama3.1:8b` latency** — still open, and it turns out
   this can't be done from a headless/CI context: `acp-ollama` has
   `external:false` ingress (internal-only) and scales to zero, and the app's
   digest endpoint is behind Google SSO. To get the number: sign in to the live
   app and time a compliance-digest generation, OR hand me the E2E test key so a
   headless request can bypass SSO. Container config: 4 CPU / 8Gi, CPU-only,
   scale-to-zero — so the first request pays a cold model-load of the ~4.7GB 8B
   weights on top of CPU inference (expect tens of seconds cold, less warm —
   estimate, NOT a measurement).
3. **ADO review-cadence** — standing reviewer vs. bypass-as-needed for future
   PRs. Bypass-policies permission is already granted; this is a process
   choice, not a technical one.

---

## P3 — In-flight in another concurrent session — do not touch

> **Almost certainly resolved — verify before acting on anything here.** This
> section described *uncommitted* work in a shared checkout as of `9d7c7a3`,
> 387 commits and 19 days ago. Uncommitted work does not survive that; either it
> landed or it was lost. Kept verbatim rather than deleted because it names the
> files that were contested, which is useful history if a conflict shows up —
> but treat every "do not touch" below as expired until re-confirmed.

A second autonomous session ("T") has uncommitted work sharing this same
checkout as of this snapshot. This is **not this backlog's to implement** —
listed here purely so nobody mistakes it for abandoned/stale work and reverts
it:

- Publish rewrite + per-file rescore (`api/handlers.py`, `api/routes/scans.py`,
  `api/store.py` — `record_publish`, `refresh_scan_aggregate`,
  `get_file_record`)
- DB-backed HITL queue touching several frontend views (`App.jsx`,
  `Dashboard.jsx`, `EmptyState.jsx`, `FileDrawer.jsx`, `Overview.jsx`,
  `Publish.jsx`, `Remediate.jsx`, `api.js`)
- Test-corpus reorg — deleting the 100 files under `test-corpus/files/` in
  favor of a new `test-corpus/bulk-200/` + `test-corpus/Legal sample files/`
  layout

If you're picking up this backlog cold and `git status` still shows these
paths modified, **stash them (`git stash push -u -m "..."`) before touching
`api/store.py` or any of the frontend files above** — don't edit over a
stash, and don't commit paths you didn't intend to touch. See the isolation-
dance pattern used for the `RULE_FORMATS` change in `16581bd` if `store.py`
needs another edit while T's WIP is still live: edit the working copy
in-place first, then build a separate clean-`HEAD`-based copy (same edits,
`assert count==1` string replace) to actually stage and commit, then restore
the mixed working copy afterward.

**Gotcha hit during the P1 work (`a916068`):** the "save the mixed copy"
step must happen *after* editing the working copy in place, not before —
saving it first and editing second means the later restore silently reverts
your own edit from the working tree even though the commit itself is fine
(git history stays correct; only the local file drifts). `test_rule_formats.py`
caught this immediately on the next isolation dance because the derived
truth no longer matched `RULE_FORMATS` — that's exactly the kind of drift
the contract test exists to catch, but don't rely on it; get the copy order
right: **edit in place → save mixed copy → build clean-HEAD copy → commit →
restore mixed copy**.

---

## P4 — Certification report as an audit artifact (report presentation)

Theme (external feedback + review, 2026-07-09): the report is a solid *scan
summary* but not yet persuasive to the three audiences that matter —
**executives** ("are we compliant?"), **auditors** ("can I trust this?"),
**remediation teams** ("what exactly changed?"). It states *what* happened but
under-proves *why to trust it*. Most of the data already exists; the work is
**consolidating it into one downloadable per-document certificate**, not new
detection.

**Hard rule for this whole section (ADR 0016 / `4fc6bc1`):** every number is a
real, derivable ratio shown with its basis, or it is omitted. NO fabricated
percentages ("96% effort saved", "AI 92%", invented "4.2s avg"). A fabricated
figure on an evidence document is spotted instantly by an auditor and *lowers*
trust — the honesty discipline is a feature to surface, not a gap to paper over.

Where the data already lives (so these are consolidation, not net-new):
`store.get_remediation_diffs` (before→after, `remediation_diff`),
`store.list_applied_fixes` (real AI values + thumbnails, `applied_fixes`),
`hitl_queue` (approvals, `approved_value`, `proposals`, `validated`),
`decision_log` (immutable who/what/when), `confidence.js` (evidence-based
High/Med/Low + basis), the stamped rubric hash + `RULE_FORMATS`/manifest
(what actually ran), and `api/report.py` (the estate PDF to extend, or add a
per-document certificate renderer alongside it).

### Flagship
| # | Item | Value | Effort | Notes |
|---|---|---|---|---|
| R1 | **Per-issue Remediation Evidence Portfolio** (consolidates the "per-issue appendix" + "before/after gallery" + "AI reasoning" asks). One mini-section per finding: thumbnail, WCAG + plain-English issue, **before → after**, AI recommendation **+ its rationale/OCR-grounding**, human decision (approved/edited/rejected), validation PASS, timestamp/reviewer/trace-id. | Highest — turns summary → audit artifact | M · 2–3 d | All data exists (`remediation_diff` + `applied_fixes` + `hitl_queue` + `decision_log`). Render into the PDF (`report.py`) and/or a per-doc HTML→PDF. Scope to remediated/failing findings, not all 87 SCs. |

### Quick wins — data exists, mostly presentation (each XS–S)
| # | Item | Notes |
|---|---|---|
| R2 | **Certification-decision block** at the top of each document (Status 🟢 CERTIFIABLE / WCAG 2.1 AA / date / reviewer / remediations applied / validation PASS / risk). | The first thing an exec reads. "Digital signature" must be a **real** SHA-256 of the artifact/bytes, never decorative. |
| R3 | **Why-certifiable prose** — one sentence replacing bare "100%": "meets all *evaluated* AA criteria after remediation + re-scan validation; no blocking findings remain." | Cheap, high trust. Pair with R-A (scope). |
| R4 | **Certification-metadata / chain-of-custody** section — surface prominently (not buried in the header): document SHA-256, scan SHA-256, rubric version + hash, model version, validator version, timestamp, reviewer. | Partly exists (scan hash + rubric version). Enterprise-critical; low effort. |
| R5 | **AI reasoning inline** — show the fix rationale / OCR-grounding / confidence *basis* (not a number). | **Now shipped as data** via the proposal lane (`proposals[].rationale`, `describe_image_structured` grounding, `confidence.js` basis) — just render it. |
| R6 | **Richer file inventory** — per file: ✓ Certified · N detected · N remediated · N remaining · N human approvals · validation PASS. | `report.py` inventory today shows only Status/Score/Findings. |
| R7 | **Explain the score** — "100 = no blocking findings remain, all required remediations re-scan-validated, AA-certifiable." | One line. |
| R8 | **POUR (Perceivable/Operable/Understandable/Robust) breakdown** — real per-principle pass ratios. | Deterministic → honest by construction. |

### Honesty-gated — agree only if computed from real data
| # | Item | Guardrail |
|---|---|---|
| R9 | **Human-review KPI block** (reviewed / auto-remediated / edited / rejected / effort). | Derive counts from `hitl_queue` + `decision_log`. "Avg review time" only if real timestamps exist; "effort saved" only as (auto-cleared ÷ total findings) with that basis shown — else OMIT. |
| R10 | **Assurance/confidence bars** (deterministic vs AI vs human). | Reframe as real ratios: e.g. "fixes that cleared re-scan ÷ fixes attempted", "deterministic SCs ÷ evaluated SCs". No invented "92%". |
| R11 | **"How ACP reached this decision" methodology** (rules executed, OCR, revalidation, approvals, final cert). | The rule count must be the **actual** number run for *this* document (from the manifest/`RULE_FORMATS`), not a marketing figure. |
| R12 | **Compliance timeline** (scan → findings → AI recs → human review → remediations → validation → certified). | Narrative of the real pipeline; counts from the same sources. Cheap. |

### Larger / has a dependency
| # | Item | Notes |
|---|---|---|
| R13 | **Manual-verification instructions** — per-format independent-verification steps (Word/PowerPoint Accessibility Checker, macOS Accessibility Inspector, NVDA/VoiceOver/JAWS) with expected results. | Genuinely differentiating (lets an auditor independently confirm). Keep generic per-format — never doc-specific claims. Medium. |
| R14 | **Per-criterion evidence-of-compliance rows** (rule executed · PASS · evidence/page/object · validation method). | Overlaps the coverage manifest; scope to failing/remediated criteria only or it's a 200-row dump. |
| R15 | **QR code → immutable online report** (audit trail, remediation history, verification log, version history). | Needs a hosted **immutable** artifact + a versioned verification endpoint. Partially there via Blob remediated copies + publish; the immutability/versioning guarantee is the real work. Larger. |

### My additions (review, 2026-07-09) — weighted toward *auditor* trust
| # | Item | Why |
|---|---|---|
| R-A | **Scope-of-assertion / negative-assurance statement** (HIGH). Per document: "N of 87 SCs auto-validated, M human-reviewed, K not-applicable-to-this-format, and these SCs were NOT evaluated (captions, timing, keyboard-trap, …)." | The single most important auditor-trust item and an over-claim guard: prevents "100%" being mis-read as full WCAG conformance. On-brand with the certifiable/uncertain/unanalysable distinction already in `report.py`. |
| R-B | **Immutable audit-log excerpt** — render this document's `decision_log` rows inline (who approved what, when, with the approved value). | The evidence backbone that directly answers "can I trust this." Data already immutable + append-only. |
| R-C | **Per-fix assurance-level disclosure** — distinguish deterministic-and-re-scan-cleared vs AI-generated-and-human-approved vs AI-generated-and-re-scan-validated-but-not-human-confirmed. | Uses the proposal lane's `validated`/`subjective` signals + `remediation_state`; tells the reader exactly what assurance each fix carries instead of a flat "PASS". |
| R-D | **Reproduce-this-result instructions** — "re-run: POST /scans with rubric hash `<h>`; expect identical findings." | Pairs with R4 chain-of-custody; makes reproducibility actionable, not just asserted. |
| R-E | **"Supersedes" lineage** — "this certificate supersedes cert `<id>` from `<date>`" (per-document version chain). | Extends the estate-level velocity section already in `report.py` to a per-document custody chain. |

Sequencing suggestion: R1 (flagship) + R2/R3/R6 + R-A first (they land the biggest
trust jump on data that already exists), then R4/R5/R11/R-B/R-C, then the
honesty-gated KPI/bars (R9/R10) once the real ratios are wired, then R13–R15/R-D/R-E.

---

## Reference — where things live

- `api/office_structure.py` — first-party docx/pptx/pdf/xlsx structural
  checks (2.4.6, 2.4.9, 1.4.3, 1.4.6, 2.4.1, 3.3.2); dispatcher is
  `checks_for(path, ext)`.
- `api/store.py` — `RULE_CATALOG` (the 87-ish rule list) + `RULE_FORMATS`
  (per-rule format applicability) + `_rule_outcome()` (PASS/FAIL/NOT_APPLICABLE).
- `tests/test_rule_formats.py` — contract test deriving `RULE_FORMATS` truth
  independently from source; extend `_derive_formats()`/`_OFFICE_STRUCT_FORMATS`
  whenever a P1 item above lands.
- `frontend/src/wcagCatalog.js` / `wcagCatalog.test.js` — the human-facing
  coverage table + its drift guard (source must be backed by a real validator,
  not just an aspirational label).
- `spike/dotnet/AcpScan.Cli/Program.cs` — the partner engine boundary; we
  cannot extend partner rules ourselves, only add first-party checks
  alongside them (the `office_structure.py` pattern).
