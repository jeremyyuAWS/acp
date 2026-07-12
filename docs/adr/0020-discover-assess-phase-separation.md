# ADR 0020 — Separating Discover (inventory) from Assess (conformance)

Status: **Accepted** (2026-07-12) — **Rollout stage 3 + 4 shipped** (2026-07-12): the file-open + WCAG analysis moved out of Discover and into Assess, behind `ACP_DEFER_ANALYSIS_TO_ASSESS` (deploy default ON, instant env revert). Discover now LISTS only — `classify_from_metadata` (mime/ext → `doc_class`, no bytes), a `scan_inventory` row per file, run status `discovered`, NO analysis enqueued. `scan_assess` (fired by `POST /scans/{sid}/assess`) rebuilds the download+analyse fan-out from the inventory + persisted params, flips the run to `running`, and the existing per-file jobs + `scan_finalize` take over; `assessed_at` is stamped at finalize. Kept deliberately low-risk: `file_records` still mean ASSESSED results and fill 0→N only during Assess, so the finalize counter (`count_files_done`) + exactly-once finalize (ADR 0013) are UNTOUCHED; `get_scan` surfaces the inventory as `discovered` rows so Discover shows the estate before anything opens; cross-scan incremental reuse still works (keys on Drive md5, evaluated at Assess); AssessRunner polls the real analysis and reveals results from the freshly-scored files. Tradeoff: Discover no longer shows per-file page/image COUNTS (those need the bytes — they appear after Assess). — **Rollout stage 2 shipped** (2026-07-11): `api/classify.py` (cheap container peek — page/slide/sheet counts, image count, has_text/has_images/is_scanned → `doc_class`; no rule engine, never raises), persisted additively on the `documents` table (nullable columns + `classified_at`, `upsert_document(classify=…)`, ON CONFLICT preserves a prior classification when a later triage-only upsert omits it), wired on all three scan paths (fan-out `analyse_and_assess`, the monolithic thread body + report assembly). Findings are unchanged — classification is produced alongside today's analysis, per §Rollout 2. Validated on the real corpus (Husqvarna deck → slide-deck, 11 slides / 61 images; xlsx → spreadsheet, 7 sheets). **Rollout stage 1 shipped** (2026-07-11): `blob.upload_source`/`download_source` (`sources` container, `{owner}/{scan_id}/{filename}`, lazy-create, no-op unconfigured) + `scanner.cache_source_bytes` wired after BOTH download paths (monolithic `run_scan` read loop and the ADR 0007 fan-out per-file body). Best-effort, nothing reads from it yet — behavior unchanged, exactly as §Rollout 1 specifies. Dedup'd fan-out files intentionally skip the write (their bytes live under the prior scan's key; the stage-3 reader falls back).
Date: 2026-07-12
Related: [ADR 0001](0001-read-only-assessment-spine-on-mdk.md) (the read-only scan spine this re-phases), [ADR 0003](0003-document-lifecycle-model.md) (documents table + triage scorer — the inventory home this builds on), [ADR 0007](0007-fan-out-scan-pipeline.md) (the durable fan-out this extends to a second phase), [ADR 0011](0011-incremental-scan-fingerprinting.md) (the per-file fingerprint that decides what to re-assess), [ADR 0016](0016-evidence-based-confidence.md) (honesty — a document with no assessment has *no* findings, not zero findings)

## Context

The product's mental model — and the one the customer (Deva) is explicit about keeping clean — is a pipeline of **distinct activities**:

> **Discover** (what documents do we have?) → **Assess** (what's wrong with them?) → **Remediate** → **Review** → **Certify** → **Monitor**

The UI presents these as separate tabs with separate CTAs ("Assess 150 files" is a deliberate, explicit action gated behind Discover). The results views (Overview / Dashboard / Monitor) already gate on an explicit `mark_assessed` flag, and `POST /scans/{id}/assess`'s own docstring draws the line: it writes "the WCAG rule assessment … separate from the scan trace (which is discovery + deep-scan only)."

**But the engine does not honor that line.** The single `scanner.run_scan` pass, triggered by the Discover flow (`startScan` / `startScanQueued`), runs everything up front:

```
connect → discover (list files) → read (download) → ANALYSE → score
                                                     └── opens every file and runs the FULL
                                                         WCAG engine: .NET OpenXML analysers,
                                                         PDF/HTML analysers, OCR images-of-text
                                                         (1.4.5/1.4.9), sensory + language +
                                                         reading-level text checks, contrast,
                                                         headings, PII.
```

`POST /assess` then opens **not a single file** — it calls `mark_assessed`, enqueues an `assess_trace` Langfuse job, and un-gates the results views. The conformance evaluation already happened at Discover time.

Two problems follow, one conceptual and one operational:

1. **The boundary Deva cares about is fiction.** "Discover" already performs the WCAG analysis that is definitionally an Assess activity. Nothing about the current architecture *enforces* that Discover only inventories — a reviewer who trusts the tab labels is being misled about what ran when, which is exactly the transparency posture the rest of the product (provenance, trust states, ADR 0016) is built to uphold.
2. **Work is done that may never be wanted.** Every discovered file is fully analyzed — OCR'd, text-extracted, run through the .NET engine — even if the user never assesses it, scopes it out, or only wants an inventory of a 100K-file estate. On large estates that is the dominant cost, spent before the user has decided what is in scope.

The counter-pressure (why it was built this way) is real and must be respected: **front-loading opens each file once.** A naïve split re-opens (and, for Drive/SharePoint, re-downloads) every file twice — once to inventory, once to assess.

## Decision

**Split `run_scan`'s monolithic pass into two explicitly-triggered phases with a persisted content cache between them, so Discover produces inventory only and Assess produces conformance findings — without opening any file twice.**

The dividing question is precise and defensible to an auditor:

- **Discover answers "what is this?"** — identity and inventory metadata that describe the artifact.
- **Assess answers "what's wrong with it?"** — every WCAG success-criterion evaluation.

Reading a slide count or detecting that a deck *contains* images is inventory. Deciding those images *lack alt text* is conformance. That line is the contract.

### A. Discover = inventory + light classification (no rule engine)

`run_scan` keeps `connect → discover → read`, then runs a new **`classify`** step in place of `analyse`. `classify` opens each downloaded file only far enough to record inventory-grade metadata, and runs **none** of the WCAG detectors:

- identity + existing fields: name, ext, size, owner, department, source, drive/sp id, ADR 0011 content fingerprint;
- **structural counts** from a cheap container peek: page/slide count, table count, image count, `has_text` / `has_images` / `is_scanned` booleans (an OOXML `media/` listing or a PDF page count — a zip directory read or a pdfium page count, not a shape walk);
- **document-class** from ADR 0003's existing triage scorer (already inventory-time), enriched with the counts above.

This lands in the ADR 0003 `documents` table (the inventory's existing home). **No `issue_records` rows are written at Discover time.** The Discover tab and its FileDrawer show inventory and a *classification*, never a WCAG finding.

Honesty consequence (ADR 0016): a discovered-but-unassessed document reports **"not yet assessed"**, never "0 issues". Zero findings is a claim Assess earns; absence of assessment is not conformance.

### B. Persisted content cache — open once, assess later

To keep the "open each file once" property across the phase boundary, `read` writes each file's bytes to the **ADR 0010 blob seam** (`{owner}/{scan_id}/{filename}` in a `sources` container), the same mechanism the render/thumbnail seam already uses. Assess reads from that cache, not from a second Drive/SharePoint download. No-op (re-download on assess) when `ACP_BLOB_ACCOUNT` is unset — exactly today's degradation for the thumbnail cache, so local/dev is unchanged. TTL and eviction reuse ADR 0010's policy.

### C. Assess = the conformance phase (the current `analyse_and_assess` body, moved)

`POST /scans/{id}/assess` becomes the trigger that **actually evaluates conformance**, not just a trace-write:

- It enqueues, per in-scope file, an **`assess_file`** durable job — a second fan-out phase reusing the ADR 0007 discover→scan_file→finalize machinery and its atomic finalize-once counter.
- `assess_file` loads bytes from the §B cache and runs the **existing** `analyse_and_assess` body verbatim — the .NET engine, PDF/HTML analysers, OCR, text checks, contrast/headings, and (if the deep-scan opt-in is set) PII. This is a **move, not a rewrite**: the analyzer code is untouched, only *when* and *behind which trigger* it runs changes.
- It writes `issue_records` (with ADR 0018 geometry) and the scan aggregate, then `mark_assessed` + the `assess_trace` Langfuse span as today.
- **Scope is honored.** Assess evaluates only files in the current scope (triage decisions, level, exclude-remediated) — the estate-scale win: inventory 100K, assess the 2K in scope.
- **Incremental (ADR 0011).** `assess_file` skips a file whose fingerprint + rubric hash are unchanged since its last assessment, reusing prior findings — so re-assess is cheap and only changed files re-run.

### D. Compatibility — the one-click path stays one click

The demo/eval flow ("scan and see results") must not become two mandatory clicks. Preserve it with an **`assess=true` scan parameter** (default **false** for the API; the Discover UI's explicit "Assess" CTA is the honest path) that chains the assess phase immediately after classify in the same run — so `startScan(assess=true)` reproduces today's end-to-end behavior for scripts, the E2E test, and any caller that wants it. The tab-driven UI passes `assess=false` and drives Assess as its own step. No public shape is removed; `/assess` keeps its route and now does the analysis it always claimed to gate.

## Consequences

- **The boundary becomes real, not labeled.** Discover cannot emit a WCAG finding because the rule engine no longer runs there — the separation is enforced by construction, which is the property Deva asked for and the one a labeled-but-unenforced boundary can't give.
- **Estate-scale cost tracks scope.** Inventory is cheap and always runs; the expensive conformance pass runs only on in-scope files, only when Assess is triggered. A 100K-file discovery no longer pays 100K analyses up front.
- **"Open once" is preserved** via the §B blob cache — the property that justified front-loading is kept without front-loading the analysis.
- **Assess gains honest progress + per-file durability.** Because Assess is now its own ADR 0007 fan-out, the UI can show real "assessing 412 / 2,000" progress (today the analyse phase is inside the scan), and a crash mid-assess resumes per-file instead of restarting the estate.
- **Findings are a moved body, not new code.** `analyse_and_assess` runs unchanged; the risk is in *plumbing* (trigger, cache, fan-out phase), which is testable in isolation, not in the detectors.
- **Migration is additive (rule 5).** New `documents` inventory columns and a `sources` blob container are `ADD`-only; `issue_records` is unchanged; the `assess=true` compat flag means no existing caller breaks. Existing already-assessed scans are unaffected (they carry findings already).
- **A visible product change: Discover shows classification, not findings.** This is the intended outcome, but it *is* a UX shift — the Discover tab's counts move from "issues found" to "documents / types / not-yet-assessed", and issue counts appear after Assess. Called out here because it changes numbers a user sees (rule 5 flag).

## Rollout (staged — each independently shippable, behind flags)

1. **Cache seam.** `read` writes source bytes to the ADR 0010 blob (`sources` container); no behavior change yet — analysis still runs at scan. Verifies the cache round-trips before anything depends on it.
2. **Classify step.** Add the light `classify` metadata (counts/booleans) to the `documents` table at scan time, alongside the existing analysis. Discover UI can start showing classification; findings still produced as today. Reversible.
3. **Assess fan-out.** Introduce `assess_file` reading from the cache; make `/assess` enqueue it. Run it in *shadow* first (compare its findings to the inline scan's — they must be identical, since it's the same body) before flipping.
4. **Flip the default.** Move `analyse_and_assess` out of `run_scan` behind `assess` (default false); Discover UI passes `assess=false`; `assess=true` preserves the one-click/E2E path. This is the switch that makes the separation real; everything before it is reversible groundwork.

## Non-goals

- **Re-writing any detector.** The WCAG analyzers, OCR, and text checks are moved verbatim; their behavior is out of scope. If the shadow run in step 3 shows any finding delta, that is a plumbing bug, not a detector change.
- **Removing or renaming `/assess`, `/scans`, or the scan params.** Compat is preserved; `assess=true` reproduces today's flow. Deprecation, if ever, is a later ADR.
- **A third "Classify" tab.** Classification is inventory metadata surfaced *within* Discover, not a new pipeline stage in the UI — the user-facing stages stay Discover → Assess.
- **Changing what conformance means.** Same rubric, same rules, same level gating (ADR 0001). Only *where in the pipeline* the evaluation runs changes.
- **Caching bytes when there is no blob store.** Without `ACP_BLOB_ACCOUNT`, Assess re-reads the source (re-download for Drive/SharePoint) — the honest local/dev degradation, not a silent inconsistency.
