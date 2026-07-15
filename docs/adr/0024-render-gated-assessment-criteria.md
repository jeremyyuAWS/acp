# ADR 0024 — Render-gated assessment criteria (Resize / Reflow / Text Spacing + the 1.4.3 hybrid)

Status: **Proposed** (2026-07-15)
Date: 2026-07-15
Related: [ADR 0018](0018-slide-page-rasterization-and-shape-geometry.md) (**the seam this rides** — `render.py::render_page_png(data, ext, page)` + `geometry.py::shape_bbox(...)`, LibreOffice→pdfium, worker-only, `ACP_OFFICE_RENDER`), [ADR 0023](0023-two-axis-assessment-remediation-model.md) (the two-axis model — these are its deferred Phase 4; all land in the 🟡 review lane), [ADR 0016](0016-evidence-based-confidence.md) (**the governing honesty constraint** — real measurement or nothing, never a fabricated pass or a made-up number), [ADR 0015](0015-page-render-thumbnail-seam.md) (rendering is **never in the scan path**), [ADR 0020](0020-discover-assess-phase-separation.md) (the deferred-enrichment pattern the render pass follows).

> Naming note: this is a **new** ADR, not a rewrite of ADR 0018. ADR 0018 already exists and is Accepted — it built the rasterization + per-shape-geometry *seam* for the review card's **visual evidence** (where a finding is). This ADR is the separate, still-open decision about the four WCAG **criteria** whose *conformance* can only be judged with rendering, which consume that seam. ADR 0023 tracks it as "#185 — render-gated, behind ADR 0018."

## Context

Four of the twenty document-core criteria are **render-dependent**: their pass/fail cannot be read from the OOXML/PDF structure alone, because the failure only appears in the laid-out, rendered artifact.

- **1.4.4 Resize Text (AA)** — text must scale to 200% without loss of content or function. Whether a text box clips or overflows at 200% is a *layout* fact.
- **1.4.10 Reflow (AA)** — content must reflow to a 320px-equivalent width without two-dimensional scrolling. Wide, fixed-layout content (broad tables, absolutely-positioned objects) is the risk.
- **1.4.12 Text Spacing (AA)** — applying the WCAG text-spacing overrides (line-height 1.5×, etc.) must not clip content — again a *rendered* outcome.
- **1.4.3 Contrast (Minimum) — the hybrid tier.** The deterministic core (ADR 0023) already certifies text over an **explicit solid fill**. It cannot judge text over a **gradient, image, screenshot, chart, or SmartArt**, because the effective background is a *rendered* pixel field, not a declared colour.

Today all four are ⚪ N/A for office/pdf in the capability table — honestly, because no static check reaches them. ADR 0023 parked them as Phase 4 "behind ADR 0018." The seam ADR 0018 built (rasterize any page of Office/PDF via headless LibreOffice → pdfium; real per-shape rectangles) is exactly the missing capability — but it is deliberately **lazy and out of the scan path** (rule 10 / ADR 0015): a document that can't render degrades to "no visual", never to a failed scan. Any assessment that leans on rendering must inherit that constraint, or it re-introduces the very coupling ADR 0018 was careful to avoid.

So the honest per-document answer for these four is not a silent ⚪, and it is emphatically **not a green pass** — ACP cannot certify layout conformance. It is: *"here is a concrete structural signal that this criterion is at render-risk; a human confirms against the rendered page."* That is the 🟡 Review Recommended lane (ADR 0023). This ADR is how those 🟡 detectors are built without violating the non-blocking rendering rule.

## Decision

**Add these four criteria to the 🟡 review lane in two tiers, split by cost, both advisory and evidence-backed (ADR 0016):**

- **Tier A — structural proxy, scan-time, always-on, no rendering.** A cheap, deterministic OOXML signal raises a 🟡 REVIEW finding with concrete evidence. Runs in the normal scan alongside the other `office_structure` checks; adds no rendering to the scan path.
- **Tier B — render-verified, deferred, on-demand, rides ADR 0018.** When a reviewer opens the finding (or an explicit "verify layout" action at Assess), the ADR 0018 render seam rasterizes the specific page(s) and *measures* the risk, upgrading the Tier-A flag from "possible" to "measured (here is the pixel evidence)." Never in the bulk scan path — same deferred-enrichment posture as the thumbnail/geometry (ADR 0018/0020).

Every finding is **🟡 review / 👤 human** on the two axes: ACP surfaces the risk, a person judges conformance, and there is no ACP fix (you cannot safely auto-rewrite a document's layout). None of them can ever become 🟢 — layout conformance is not certifiable from a file.

### Tier A — the structural proxies (ship first)

| Criterion | Tier-A signal (OOXML, deterministic) | Evidence on the 🟡 finding |
|---|---|---|
| 1.4.10 Reflow | a table with ≥ N columns (default 8), or an absolutely-positioned / fixed-size floating object | "table is 14 columns wide — may need 2-D scrolling to read at 320px" |
| 1.4.4 Resize Text | a text box with auto-fit **off** (`<a:spAutoFit>` absent / `<a:noAutofit>`) whose text length materially exceeds its box area | "text box has fixed size with no auto-fit — text may clip when enlarged" |
| 1.4.12 Text Spacing | fixed, exact line-height (`<w:spacing w:lineRule="exact">` / pptx `<a:lnSpc><a:spcPts>`) on body text | "exact line spacing set — user text-spacing overrides may clip lines" |
| 1.4.3 hybrid | a text run whose shape fill is a **picture/gradient/chart** (not `<a:solidFill><a:srgbClr>`), i.e. text over a non-solid background | "text sits over an image/gradient — contrast can't be read from colours alone" |

These are the same class of high-precision structural facts the shipped Phase-1b detectors use (controls, colour-only, focus order); they are advisory because a passing-the-proxy document can still be fine (a wide table with a horizontal-scroll affordance; text that happens to fit). New `office_structure` checks behind `checks_for`, wired into `store.REVIEW_FORMATS` + the frontend `REVIEW_ONLY` set exactly like the Phase-1b criteria.

### Tier B — render-verified enrichment (rides ADR 0018)

Deferred, on-demand, worker-only, `ACP_OFFICE_RENDER`-gated, bounded by the existing `ACP_OFFICE_RENDER_TIMEOUT` and a per-request page cap (the OCR-cap precedent). Each upgrades a Tier-A 🟡 from "possible" to "measured", or clears it to a confident "no issue found — verify" when the render shows the risk didn't materialize (still 🟡, never a certified pass):

- **1.4.3 hybrid** — `render_page_png(data, ext, page)` at 1× → sample the rendered pixels under the run's `shape_bbox(...)` rectangle → compute the real min contrast of the run colour against the *actual* background field. Genuinely-ambiguous busy backgrounds stay 🟡; a clearly-failing sample becomes a measured 🟡 with the ratio. (This is ADR 0023's "AI-assisted tier for text over gradients/images" made concrete and deterministic where the pixels allow, AI-assisted only where they don't.)
- **1.4.4** — render the box and measure how much of it the text fills; enlarging to 200% needs ≥2× that height (`render_verify.measure_resize_headroom`). SHIPPED (Tier B.2). *1.4.12 split out below.*
- **1.4.12 Text Spacing** — **SHIPPED as a *structural* measurement, not a render** (like 1.4.10, and for the same reason — the render-with-overrides plan was heavy and the clip is inferable from the file). The risk of EXACT (fixed) line spacing is that the line box can't grow, so `office_structure._min_exact_line_height_ratio` measures the tightest fixed line height as a multiple of the font size, straight from the OOXML (docx `w:line` twentieths-pt ÷ `w:sz` half-pt; pptx `a:lnSpc/a:spcPts` ÷ `a:rPr sz`, both hundredths-pt). WCAG Text Spacing needs ≥1.5×; below 1.0× the box is already shorter than the text (lines overlap). The Tier-A finding is enriched in place at scan time (no render); abstains when no font size is declared (ADR 0016).
- **1.4.10** — ~~render at a 320px-equivalent width; detect content requiring horizontal scroll~~ **SHIPPED as a *structural* measurement, not a render.** Office documents are fixed-canvas: a slide/page does not reflow when the viewport narrows, so "render narrow → detect horizontal scroll" measures nothing (it just renders the same fixed layout smaller). The honest, cross-format (docx + pptx) measurement is the **narrowest column's share of the table width**, read straight from the OOXML `gridCol` widths (twips / EMU) — scale-invariant, so it holds on any screen: `office_structure._narrowest_column_fraction`. The Tier-A finding is enriched in place ("…narrowest column is only 4% of the table (≈13px on a 360px phone) — verify it stays readable"). Deterministic and cheap, so it runs at scan time (no render, no endpoint); returns nothing when the widths aren't declared (real measurement or nothing, ADR 0016). This supersedes the render-based plan above for 1.4.10.

### Honesty guardrails (ADR 0016, non-negotiable)

1. **Real measurement or nothing.** Tier B reports a ratio/overflow it actually sampled from rendered pixels, or it abstains. A guessed contrast over a photo is worse than none.
2. **Never a pass.** These four can only ever produce 🟡 REVIEW or ⚪ N/A per file — never a certified 🟢. Consistent with the #174 audit + #188 fix: a render-lane criterion with no finding reads "verify", not a green pass.
3. **No fabricated numbers.** No confidence %. A Tier-A proxy says "may" / "at risk"; only Tier B attaches a measured value.
4. **Degrade, don't fail.** No LibreOffice / render disabled / timeout / unattributable geometry → the finding stays at its Tier-A 🟡 (or ⚪), and the scan/assess never errors.

## Blast radius / compatibility

- **Additive review-lane entries.** `store.REVIEW_FORMATS` + frontend `REVIEW_ONLY` gain `1.4.4 / 1.4.10 / 1.4.12` (office) and extend `1.4.3` beyond its 🟢 solid-fill core into a 🟡 hybrid tier for non-solid backgrounds. The four flip from ⚪ N/A to 🟡 in the scorecard / grid / drawer — no 🟢 pass is ever added. The reclassification-audit table (ADR 0023) updates these cells from ⚠ to 🟡.
- **1.4.3 is now two-lane** (🟢 auto for solid fills, 🟡 review for complex backgrounds). The per-file resolver picks the lane by whether the run's background is solid — the deterministic pass on solid text is untouched; only previously-unassessable text gains a 🟡.
- **No scan-path rendering.** Tier A is pure OOXML. Tier B reuses ADR 0018's lazy render endpoints; the bulk scan is unchanged and never slower. `ACP_OFFICE_RENDER` (worker/render image) already gates the heavy LibreOffice dependency; Tier B is dark on any build without it.
- **No storage-schema change.** Tier-A findings ride existing `issue_records` / `scan_rule_traces` (severity REVIEW) like the shipped detectors; Tier-B measurements attach to the finding at view time, not at rest.
- **Publish gate unaffected** — 🟡 is advisory and never blocks certification.

## Alternatives considered

- **Wait for full rendering and skip the structural proxies.** Rejected — Tier A ships honest 🟡 guidance now with zero rendering cost; gating all four on the render pass leaves them ⚪ (silently unassessed) in the meantime, understating what ACP can already flag.
- **Run the render pass inside the scan.** Rejected — violates rule 10 / ADR 0015 (rendering never in the scan path); a 60s LibreOffice convert per file would wreck 10K-file estate throughput. Deferred, capped, on-demand is the only posture consistent with the seam.
- **Rasterize + vision-model everything (let an LLM eyeball the page).** Rejected as the primary path — most of these are measurable deterministically (pixel-sample contrast, glyph-clip detection) once rendered; a model adds cost, latency, and a fabrication surface (ADR 0016). AI is reserved for the residual genuinely-ambiguous background cases, per ADR 0023.
- **Fold into ADR 0018.** Rejected — 0018 is Accepted and scoped to *visual evidence* (where a finding is); mixing *assessment of new criteria* into a shipped seam ADR muddies both. This rides 0018, it doesn't amend it.

## Rollout

1. **Tier A** — the four structural-proxy detectors in `office_structure` + `REVIEW_FORMATS`/`REVIEW_ONLY` wiring + unit tests (same shape as the Phase-1b detectors). Ships independently, no rendering.
2. **Tier B.1 — 1.4.3 hybrid** — pixel-sample contrast under `shape_bbox` geometry on the rendered page; the highest-value, most-deterministic render upgrade.
3. **Tier B.2 — 1.4.4 / 1.4.12** — 200%-render clip detection (+ text-spacing override for 1.4.12).
4. **Tier B.3 — 1.4.10** — ~~narrow-width reflow render check~~ shipped instead as the deterministic narrowest-column-fraction measurement (see the 1.4.10 note above); a render reflow check is not meaningful for fixed-canvas Office.

Target end-state for the twenty document-core criteria (folding this into ADR 0023's tally): the four move ⚪ → 🟡, taking Review Recommended to its full ~11–12 of 20 and shrinking genuine ⚪ N/A to the format-appropriate minimum — **evidence-backed guidance on 18–19 of 20**, with the 🟢 certifiable headline still held honestly separate.
