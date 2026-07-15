# ADR 0025 — PDF render-verified accessibility measurements

**Status:** Accepted (2026-07-15) — Tier A shipped in full; Tier B shipped via structural methods
(1.4.11 vector colours, 1.4.3-over-images text/image overlap). The render-verified *pixel-sampling*
enrichment and PDF 1.4.10 are documented decisions below (see [Implementation status](#implementation-status)).

## Context

ADR 0023 (two-axis capability) + ADR 0024 (render-gated *measured* criteria) closed the Office
(docx/pptx) render-gated cells — either from OOXML structure (1.4.10 / 1.4.12, structural) or from
the LibreOffice→pdfium render seam (1.4.3 hybrid / 1.4.4, `api/render_verify.py`). The **PDF column
was left behind**: on the assessment-capability table, pdf **1.4.3-over-images, 1.4.4, 1.4.10,
1.4.12, 1.4.1, 1.4.11** all sit at 🔴 "cannot assess".

The reason those cells were skipped is that PDF has **no OOXML to read** — it's a flattened page
description, so none of the Tier-A structural proxies apply. But two things are already true in the
codebase that make PDF measurable:

1. **PDF already renders** — `api/remediate_pdf._render_page_png` / `api/render.py` rasterize PDF
   pages via pdfium (ADR 0015/0018), the same primitive `render_verify` samples.
2. **PDF text carries position + size + colour** — `pdfplumber` (already a shipped dep) yields every
   character with `x0/y0/x1/top/size` and its fill colour; `pdf_contrast_checks` already reads char
   colours today.

So the same "real measurement or nothing" approach ADR 0024 took for Office can be done for PDF —
from extracted text metrics (structural-equivalent) and from sampled pixels (render-verified).

## Decision

Add **`api/pdf_render_verify.py`** — the PDF analogue of `render_verify` — plus PDF structural
metrics read from `pdfplumber` char data. On-demand and worker-only (same posture as ADR 0024
Tier B: view-time, `ACP_OFFICE_RENDER`-gated where a render is needed, degrades to ⚪/🔴 on any
extraction failure, never a certified pass — these stay 🟡 review because layout conformance isn't
certifiable from a file).

Per criterion, what PDF can honestly measure:

| Criterion | Measurement | Kind |
|---|---|---|
| **1.4.12 Text Spacing** | line gap ÷ font size from consecutive char baselines (pdfplumber `top`/`size`); tight leading below ~1.0× overlaps | structural (extracted text) |
| **1.4.10 Reflow** | ~~widest content extent vs page usable width~~ — **NOT built, left ⚪** (see [Implementation status](#implementation-status)): a fixed-layout PDF doesn't reflow, and content wider than the page's own MediaBox is degenerate/malformed rather than a reflow finding, so the proxy would near-never fire honestly | — (parked ⚪) |
| **1.4.1 Use of Color** | colour-only links (char run coloured like a link but no underline / no annotation), colour-coded runs | structural (char colour + decoration) |
| **1.4.3 over images** | extend the shipped `pdf_contrast_checks` — where a text char sits over an **image** XObject, pixel-sample the rendered background under the char bbox (`region_contrast`) instead of the declared page colour | render-verified |
| **1.4.11 Non-text Contrast** | stroke/fill colours of vector graphics from the content stream, or pixel-sampled edges, vs background | render-verified |

### Tiers (ship order)
- **Tier A — structural, no render** (cheap, from pdfplumber char metrics): **1.4.12, 1.4.1** (+ 1.4.10
  originally scoped here — parked, see below). Direct PDF analogues of the Office structural measures.
- **Tier B — render-verified, pixel sampling** (reuses `render_verify.region_contrast` + pdfium):
  **1.4.3-over-images, 1.4.11**. As shipped, both landed via lighter **structural** methods (no render);
  the pixel-sampling enrichment is the documented follow-on.

## Implementation status

Shipped and live (2026-07-15, both `acp-app` + `acp-worker`), all scan-time and structural — no
render, no endpoint, no schema change. Each is an advisory 🟡 REVIEW finding, never a certified pass.

| Criterion | Shipped as | Detector | Where |
|---|---|:--:|---|
| **1.4.12** Text Spacing | Tier A structural — tightest line pitch ÷ font < 1.15× | `pdf_text_spacing_checks` | scan-time |
| **1.4.1** Use of Color | Tier A structural — chromatic link text with no underline | `pdf_use_of_color_checks` | scan-time |
| **1.4.11** Non-text Contrast | Tier B **structural** — worst bordered `page.rect` stroke-vs-fill < 3:1 (the ADR's "vector colours from the content stream" option, not pixel edges) | `pdf_nontext_contrast_checks` | scan-time |
| **1.4.3** over images | Tier B **structural** — chars whose box sits ≥60% inside an image XObject; declared colour can't prove contrast there → flag for review. Rides the existing 1.4.3 lane (stays 🟢 at format level), like the Office 1.4.3-hybrid | `pdf_text_over_image_checks` | scan-time |
| **1.4.3** over images | Tier B **render-verified** — the follow-on: on demand, render the page (pdfium, no LibreOffice) and MEASURE the text-vs-image contrast per run via `region_contrast`, upgrading the flag to `worst_ratio X.X:1`. Endpoint `GET .../verify-pdf-contrast` re-derives runs from source (no schema change); frontend `PdfImageContrastCheck` on the finding. Degrades to the scan-time 🟡; never a certified pass | `pdf_render_verify.measure_pdf_over_image_contrast` + `office_structure.pdf_over_image_locators` | view-time |

**Deliberately not built:**

- **1.4.10 Reflow (⚪, not 🔴→🟡).** Originally Tier A. A flattened PDF is fixed-layout — it does not
  reflow at all, which is precisely why reflow *conformance* for PDF is a human/AT judgement, not a
  file-readable measurement. The scoped proxy ("content wider than the page's usable width") is
  degenerate: PDF content lives inside its own MediaBox by construction, so content that exceeds it is
  a malformed/clipped file rather than a reflow barrier — the check would almost never fire, and when
  it did it would mislead. Left ⚪ N/A honestly rather than shipped as noise. (Consistent with how
  ADR 0024 treats Office 1.4.10 as *structural where a narrowest-column signal genuinely exists*, and
  ⚪ where it doesn't.)

**Render-verified pixel sampling — shipped for 1.4.3-over-images:**

- The structural detector flags the *risk*; the on-demand endpoint now rasterizes the page and samples
  `region_contrast` per text run over the image for a real measured ratio (worst-run `worst_ratio`,
  `any_fail_aa`, honest abstain on a busy/varied background). This is the exact A→B pattern ADR 0024
  followed (structural flag first, measured endpoint second). Unlike the Office Tier B endpoints it
  needs no `ACP_OFFICE_RENDER` — pdfium rasterizes PDF unconditionally.

**Remaining follow-on (not built):**

- **Render-verified pixel-edge sampling for 1.4.11.** Today 1.4.11 uses the structural
  vector-colour option (declared stroke-vs-fill), which is a real measurement for declared colours;
  pixel-edge sampling would additionally catch anti-aliased / gradient borders. Lower value than the
  1.4.3-over-image case (where declared colour is meaningless), so deferred.

## Honesty guardrails (ADR 0016, non-negotiable)
1. **Real measurement or abstain.** A ratio/overflow actually read from the chars/pixels, or ⚪.
2. **Never a pass.** These stay 🟡 review or ⚪ N/A per file — never a certified 🟢 (a flattened PDF
   is inherently fixed-layout; the reflow/spacing criteria can't be *certified* from it).
3. **No fabricated numbers.** No confidence %. A measured value only where the data supports it.
4. **Degrade, don't fail.** Encrypted/scanned/untagged PDF, extraction error, or render disabled →
   the cell stays ⚪/🔴 and the scan never errors.

## Blast radius / compatibility
- **No scan-path cost.** Tier B is view-time/on-demand like ADR 0024; Tier A structural metrics are
  cheap enough to run at scan time (they reuse the text already extracted for other PDF checks).
- **No new dependency.** pdfium is in the image; pdfplumber/pdfminer are shipped deps.
- **No storage-schema change** — measurements attach at view time (Tier B) or enrich the finding
  detail in place (Tier A), exactly like ADR 0024.
- **PDF-only.** Nothing in the Office path changes.

## Alternatives considered
1. **Leave the pdf render-gated cells 🔴.** Rejected — PDF is a first-class format and the data is
   extractable; a whole column of 🔴 understates real capability.
2. **Full OCR + layout reconstruction.** Heavier, non-deterministic, and OOMs small containers
   (the easyocr precedent). The pdfplumber + pixel-sample path is deterministic and light.
3. **Relabel the cells ⚪ N/A.** Dishonest for 1.4.3-over-images / 1.4.1 / 1.4.12, which are real,
   measurable barriers in PDF.

## Target end-state
Achieved: the pdf column's *measurable* render-gated cells (1.4.12, 1.4.1, 1.4.11, and the
1.4.3-over-images blind spot) moved 🔴 → 🟡, taking PDF from 3 to 14 assessable of the 20-criterion
core (see [`../assessment-capability-matrix.md`](../assessment-capability-matrix.md)). The remaining
uncovered cells are honest, not gaps: **1.4.10** (⚪ — fixed-layout PDF doesn't reflow; a human/AT
judgement) and **2.1.1 Keyboard** (terminally human/AT). No static or structural measurement should
claim either.
