# ADR 0027 — GPU-assisted assessment of scanned / untagged PDFs

**Status:** Proposed (2026-07-15)

## Context

A scanned or untagged PDF is a flattened raster: no text layer, no tag tree, no reading order. The
deterministic and pdfplumber-based detectors (ADR 0024/0025) have nothing to read, so nearly every
criterion returns `not_evaluated` — the document is a **coverage black hole**. On the Accessibility
Status card (ADR 0026) it shows as a wall of "Not Automatically Assessable," which is honest but
unsatisfying: these are real, high-volume documents (agency forms, contracts, handbooks) and the
barriers in them are genuinely present — ACP just can't *read* them structurally.

Two things already exist that make these documents assessable **as review evidence**:

1. **PDF already rasterizes** — `render.render_page_png` (pdfium) turns any page into a PNG, no
   LibreOffice needed.
2. **A GPU vision path is deployed** — the RunPod scale-to-zero vision endpoint (ADR 0022) behind the
   AI gateway (ADR 0019), with consensus cross-check (`qwen2.5vl` + `minicpm-v`). It already reads
   charts and drafts alt text.

A vision+OCR+layout pass can recover text, headings, reading order, tables, and image purpose from the
page pixels — enough to move a scanned PDF from "can't assess" to **reviewable coverage**. Crucially,
heavy OCR **OOMs the 1 GiB serving container** (the easyocr lesson, #873), so this must run on the
worker tier → RunPod GPU, never inline in the fast scan.

## Decision

Add a **vision-backed assessment path for scanned / untagged PDFs only**, gated, worker-tier, opt-in,
and landing entirely in the **🟡 review lane** (ADR 0023) — evidence a human confirms, never a
certified pass.

- **`api/pdf_vision_assess.py`** — the new seam. Input: the page PNGs `render.render_page_png` already
  produces. It calls the vision model (through the AI gateway, so provider/zone/consensus are governed
  by ADR 0019) and returns a structured layout model: `{text, headings[], reading_order[], tables[],
  images[{bbox, apparent_purpose}], language}`.
- **Deterministic detection gate** — a PDF is "scanned/untagged" when it has (near-)zero extractable
  text yet image XObjects covering the page, and/or no tag tree. Native-text PDFs are untouched: they
  keep the deterministic/pdfplumber path. The gate is cheap and runs first.
- **Map recovered structure to the review lane** for the criteria vision genuinely unlocks —
  1.1.1 (images + apparent purpose), 1.3.1 (headings/structure), 2.4.6 (headings & labels),
  3.1.1 (language), 1.3.2 (reading order) — each emitted as an advisory REVIEW finding carrying the
  vision evidence (the recovered snippet + the page crop), routed like every other 🟡.
- **Feeds the Accessibility Status Coverage metric** (ADR 0026): a scanned PDF's criteria move from
  `not_automatically_assessable` to `needs_review` ("ACP could look, using vision"), lifting Coverage
  without touching the certification bar.

### Tiers (ship order)
- **Tier A — detection + extraction**: the scanned/untagged gate + `pdf_vision_assess` returning the
  layout model. No assessment wiring yet — proves "this is a scanned PDF, and here is what vision sees."
- **Tier B — review findings**: map the layout model to REVIEW findings for the unlocked criteria,
  with per-finding vision evidence (recovered text + page-region crop).
- **Tier C — provenance + consensus**: consensus cross-check (abstain on disagreement), the evidence
  header (`AI vision · OCR · consensus`, Epic 2), and the `ai_calls` provenance record (ADR 0019).

## Honesty guardrails (ADR 0016, non-negotiable)
1. **Vision output is review evidence, never a certified pass.** Every vision-derived finding is 🟡
   Needs Review; a scanned PDF can reach "Ready for Certification" only through human confirmation, the
   same as any other review lane.
2. **Abstain on low model agreement.** The consensus cross-check that guards the image path guards this
   one; disagreement → no claim, not a guess.
3. **No fabricated numbers.** No confidence %; the evidence is the recovered text + the page crop.
4. **Provenance is recorded** — model, zone (local/cloud), and consensus outcome per finding
   (`ai_calls`), so a reviewer sees exactly what produced it.
5. **Scanned/untagged only.** Native-text PDFs keep the deterministic path unchanged — vision never
   overrides a real measurement.

## Blast radius / compatibility
- **PDF-only, gated, opt-in, worker-tier.** Native-PDF and Office paths are untouched. Runs like the
  PII deep scan (explicit opt-in; heavy) and on `acp-worker` → RunPod, off the OOM-prone serving tier.
- **No storage-schema change** — findings ride the existing REVIEW lane (like the ADR 0024/0025
  detectors); provenance uses the existing `ai_calls` table.
- **No new dependency** — pdfium + the RunPod vision endpoint + the AI gateway are already shipped.
- **Operational precondition (must land first):** the RunPod API key exposed 2026-07-12 must be
  rotated and the idle pod policy confirmed before ACP leans harder on this path — see
  [[reference_acp_ollama_gpu_path]]. Azure-native GPU is still quota-ungranted, so RunPod is the path.

## Alternatives considered
1. **Leave scanned PDFs unassessable.** Rejected — a real, high-volume coverage hole; vision unlocks it
   honestly as review evidence.
2. **Deterministic OCR only (tesseract/easyocr).** Insufficient: text-only OCR recovers characters but
   not reading order, heading structure, table semantics, or image *purpose*; easyocr OOMs the
   container (#873). Vision is needed for the structural/semantic layer, and RunPod offloads the weight.
3. **Auto-classify vision findings as pass/fail.** Rejected (ADR 0016) — vision judgement is review
   evidence a human confirms, never a certification.
4. **Run it inline in the fast scan.** Rejected — heavy + GPU-bound; it belongs on the worker tier as an
   opt-in pass, exactly like PII.

## Target end-state
A scanned or untagged PDF opens with an **Accessibility Status** that reads *"Needs Review"* instead of
a wall of *"Not Automatically Assessable."* Its Coverage climbs because ACP could look — using vision —
and every vision finding carries recovered evidence a reviewer confirms in seconds. The certification
bar is unchanged: nothing vision produces is ever certified without a human. This converts a document
class competitors simply skip into first-class, reviewable coverage — the single largest honest
coverage gain GPU makes available to Assessment.
