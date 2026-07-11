# ADR 0018 — Slide/page rasterization + per-shape geometry (the visual-evidence seam)

Status: Accepted — **Slices 1–3 shipped** (2026-07-11):
- **Slice 1** — Office (docx/pptx/xlsx) + PDF page rasterization via headless LibreOffice → pypdfium2 (`render.py`, Office-aware `can_render` + `/thumbnail` + `/page/{n}` endpoints, LibreOffice in the deploy image) + the large page-preview HERO on `EvidenceCard`.
- **Slice 2** — real per-shape geometry: `api/geometry.py` reads the offending pptx `<p:pic>`'s `<a:xfrm>` from its `part#rId` locator → normalized `{page,x,y,w,h}` (slide `<p:sldSz>` + `<p:sldIdLst>` order), served by `GET …/geometry?locator=`; `Thumbnail` overlays the red box + a derived location string. Grouped/inherited/non-pptx → None (honest, ADR 0016).
- **Slice 3** — zoom-to-object: a toggle reveals a pure-CSS cropped close-up of the box (no second fetch).
- **Slice 4** — multi-image pager: for a finding with many flagged images, a `‹ Image i of N ›` control steps the hero preview + box through each one (`heroLocator` = the paged instance's locator).
Verified locally against showcase-deck.pptx (box lands exactly on each chart/diagram; crop isolates the Q4 chart). Also shipped alongside: **#129** AI audit-trail panel (real `ai_calls` ledger — model/zone/latency — on the card) and a render-flash fix (hero waits for geometry). REMAINING (deliberately deferred): per-document heatmap/mini-map (#17/#121) needs total-page data; PDF/docx/xlsx per-shape geometry (pptx-only today). NOT built — visual before/after render (#11): for the dominant alt-text fix the re-render is pixel-identical (only hidden alt changes), so it would mislead; the drafted alt TEXT is the honest "after".
Date: 2026-07-11
Related: [ADR 0015](0015-page-render-thumbnail-seam.md) (extends the render seam it built), [ADR 0012](0012-own-office-analysers.md) (the .NET OpenXML analysers that will emit geometry), [ADR 0016](0016-evidence-based-confidence.md) (the no-fabricated-number honesty rule this must respect), [ADR 0010](0010-remediated-output-object-store.md) (blob cache reused)

## Context

The HITL "reviewer trust" direction (see `docs/` PRD "Visual Evidence & Reviewer Trust") makes one demand the current card cannot meet: **the reviewer must see *where* the issue is, on the artifact, in under 10 seconds.** The mock that validated the direction leads with a large slide preview and a red bounding box over the flagged object — "the thumbnail is the hero." Everything else on the card (evidence checklist, pipeline ladder, confidence split, verify steps, cert preview) already ships as honest assembly of existing data. The visual half does not, and six vision points are blocked on the *same missing capability*:

- **#1 large preview** — office image bytes are capped at 96px (`proposals.thumb_b64 max_edge=96`) and only the embedded image is captured, never the slide it sits on;
- **#2 bounding boxes** — findings carry only a `part#rId` locator (`remediate_office.py`), **no x/y/w/h geometry**;
- **#3 zoom-to-object** and **#4 visual before/after** — need both a rendered page and the object's rectangle;
- **#11 per-document heatmap** and **#12 mini-map** — want a page grid to color.

ADR 0015 built the render seam but scoped it to **PDF, page 1 only**, and explicitly parked Office rasterization, multi-page, before/after, and bounding boxes as follow-ons. This ADR is that follow-on. Two hard constraints carry over from 0015 and the repo's posture:

1. **Non-blocking (rule 10 / ADR 0015).** Rendering and geometry must never sit in the path of scan, remediate, or report. A document that can't be rendered degrades to "no visual", never to a failed scan or a 500.
2. **License (ADR 0015 §Context, `docs/license-posture.md`).** No copyleft *linked* into the image. PyMuPDF (AGPL) and poppler (GPL) stay out. A separately-invoked subprocess binary (the tesseract precedent, #873) is acceptable.

And one honesty constraint specific to this feature:

3. **No fabricated precision (ADR 0016).** A bounding box drawn at the wrong place is worse than none — it destroys the trust the feature exists to build. Geometry must be *real* (parsed from the file), normalized deterministically, and **absent rather than guessed** when the analyser can't attribute a rectangle. "Image 3 of 14 · top-right" must be derived, never invented.

## Decision

**Extend the ADR 0015 render seam to (A) rasterize any page/slide of PDF *and* Office, and (B) capture real per-shape geometry on the finding, so the frontend can overlay boxes, crop, and zoom — all lazily, non-blocking, and degrading to today's behavior on any failure.**

### A. Rasterization — one seam, two source paths

- Generalize `api/render.py::render_page1_png(data, ext)` → **`render_page_png(data, ext, page=1)`**. The `/thumbnail` endpoint gains **`?page=N`** (default 1, preserving 0015's callers). PDF: pdfium renders page N (already page-addressable). Still `bytes | None`, still never raises.
- **Office (pptx/docx/xlsx) → PDF → pdfium**, via **LibreOffice headless** (`soffice --headless --convert-to pdf`) invoked as a **subprocess with a hard timeout** (mirrors the .NET CLI and tesseract patterns). LibreOffice is MPL-2.0 / LGPL-3.0 and is *invoked*, not linked — acceptable under the subprocess-binary precedent; it is a **heavy apt add (~400MB)** and therefore goes **only on the worker/render image, not the API tier**, and is **feature-flagged** (`ACP_OFFICE_RENDER=1`) so a build without it simply returns `None` → today's placeholder. Rejected alternative: a render mode on the .NET OpenXML CLI (ADR 0012) — OpenXML is an *analyser*, it has no layout/rendering engine; building one is far more than LibreOffice-as-subprocess.
- **Cache** reuses ADR 0010's blob seam exactly as 0015 does, keyed `{owner}/{scan_id}/{filename}#p{N}.png` in the `thumbnails` container. No-op (render-every-request) when `ACP_BLOB_ACCOUNT` is unset, as today.

### B. Geometry — real rectangles, normalized, or nothing

- **The producer of a finding also emits its bounding box, in normalized page fractions** `{x, y, w, h}` ∈ [0,1] (fraction of page width/height), plus the 1-based `page`. Normalized (not px/EMU/pt) so the box is resolution-independent — it overlays any render size the frontend picks.
  - **Office**: the .NET OpenXML analysers (ADR 0012) already walk each shape (`<a:off>`/`<a:ext>` in EMU) to raise findings. Extend them to record the shape's EMU rect and the slide size (`<p:sldSz>`) / page size, and emit `bbox = {x: off.x/W, y: off.y/H, w: ext.cx/W, h: ext.cy/H}`. Shapes without an explicit transform (inherited layout placeholders) emit **no bbox** — the box is omitted, not approximated.
  - **PDF**: `pdfplumber` already yields image/word rects in points; normalize by the page's MediaBox. Untagged/scanned figures with no attributable rect emit no bbox.
- **Storage — additive, per the compat rule (rule 5).** A nullable `bbox JSON` column on `issue_records` and the `hitl_queue.proposals[]`/`evidence[]` entry shape (`{locator, thumb, bbox?}`), via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. No existing column changes; a row without geometry is exactly today's row.
- **Derived location strings** ("Image 3 of 14 · top-right") are computed from the bbox at render time (quadrant from x/y, ordinal from the shape index) — never stored, never guessed. Absent bbox → the existing page/slide pill only.

### C. Frontend — the card already knows how

- `<Thumbnail>` (0015) gains `page` (already partially there) and renders large for image findings (the mock's 40–50% card height). A new `<EvidenceOverlay>` positions an absolutely-placed box at `left:x· top:y· width:w· height:h` (%) over the render — the exact technique in the validated mock. **Renders only when `bbox` is present**; no bbox → plain large preview, no box.
- Zoom-to-object = CSS transform to the bbox region; "show full slide" resets it (feedback: keep both). Crop-beside-full (feedback #1) = the same render with two views. Visual before/after (#4) pairs the source render with the remediated render (0015 already built the seam for a second render to "slot in later").

## Consequences

- **Non-blocking by construction**, inheriting 0015: no scan/remediate/report path calls the renderer or reads geometry to do its job; geometry emission is a cheap addition inside analysers that already walk the shapes. Worst case for any document is "no box, no preview" — the card is exactly today's.
- **The visual-first half of the trust vision becomes assembly**, like the rest: once `render_page_png(?page)` + `bbox` exist, the large preview, bounding box, zoom, crop, before/after, heatmap (#121), and mini-map are all frontend composition of real data — no per-feature backend work.
- **One heavy, isolated, flagged dependency.** LibreOffice lands on the worker/render image only, behind `ACP_OFFICE_RENDER`; the API tier and license posture are unchanged (subprocess, not linked). If the size is unacceptable, the PDF path still ships the capability for the PDF corpus with zero new deps (pdfium already vendored).
- **Honesty preserved (ADR 0016).** Every box is a parsed rectangle or absent; every derived location string is computed from a real box. Nothing is a fabricated coordinate — the same discipline that keeps confidence an enum keeps geometry a fact.
- **Cost / latency.** Office render pays a LibreOffice convert (~1–3s cold) on first view of a file, then blob-cached; PDF is 0015's few-hundred-ms. Only files a human opens get rendered. Warmable from the remediation worker later (additive), as 0015 notes.
- **Verification.** `render_page_png` is unit-testable against real corpus PDF/pptx (valid PNG signature out, `None` on garbage). Geometry normalization is unit-testable against a fixture deck with known shape offsets (a box's center lands in the expected quadrant). The overlay is validated live: the red box sits on the flagged object.

## Non-goals

- **A document viewer.** This renders specific pages a reviewer opens; it is not pagination/scroll of the whole file.
- **Editing on the render.** The box locates; remediation still writes through the existing appliers (`apply_alt.py`, the OOXML remediators). No draw-to-fix.
- **OCR-derived boxes for scanned PDFs.** If a figure has no attributable rect, it stays boxless (routed to human as today) — we don't infer a rectangle from pixels.
- **Sub-shape geometry** (a region *within* an image, a specific table cell). Shape-level rectangles only; finer geometry is a later ADR if a criterion needs it.
- **Replacing the enum confidence with a number.** Geometry is precise because it's measured; confidence stays an enum precisely because it isn't (ADR 0016).
