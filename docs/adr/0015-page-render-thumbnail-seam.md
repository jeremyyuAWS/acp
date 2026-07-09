# ADR 0015 — Page-render / thumbnail seam (lazy PDF→PNG, blob-cached)

Status: Accepted (PDF shipped); Office (docx/pptx/xlsx) Proposed
Date: 2026-07-09
Related: [ADR 0010](0010-remediated-output-object-store.md) (reuses the blob seam), [ADR 0012](0012-own-office-analysers.md) (Office render follow-on)

## Context

HITL reviewers work the "AI Work Inbox" (`ReviewCenter.jsx`) and the per-file drawer
(`FileDrawer.jsx`) against a *filename and a finding list* — they never see the document.
A reviewer eyeballing "image missing alt text on slide 1" has no way to look at slide 1.
The per-file compliance PDF (`pdfReport.js` `exportFileCertification`) is likewise all
tables and vector charts — no visual of the artifact it certifies. A single page-1 preview
image per document closes that gap in all three surfaces (and sets up before/after later).

Rasterizing a document page is net-new for the backend. Two constraints bound the choice:

1. **License.** The repo ships no `LICENSE` and is "not licensed for redistribution"
   (README); the stated intent (ADR 0010: "MIT-licensed — passes the license gate") is to
   stay on permissive deps. There is no automated gate today, so the discipline is manual:
   **no copyleft.** That rules out **PyMuPDF/`fitz` (AGPL)** outright, and makes
   **poppler (GPL)** — the binary behind `pdf2image` — a dep we'd rather not add to the
   image either.
2. **Non-blocking.** Rendering must never sit in the path of scan, remediate, or report.
   A document that fails to render (corrupt, encrypted, an unsupported type) must degrade
   to "no thumbnail," never to a failed scan or a 500.

## Decision

**Render page 1 to PNG lazily, on demand, behind one owner-checked endpoint, cached in blob.**

- **Renderer: `pypdfium2`** (Google's pdfium, BSD-3-Clause + Apache-2.0 — permissive; wraps
  no GPL). It's a **pure pip wheel that bundles the pdfium binary**, so it needs *no* system
  package — nothing added to `deploy/public/Dockerfile`'s `apt-get` line, and it works in
  local macOS dev the same as the slim Linux container. pdfium is already the engine our own
  `spike/python/worker.py` reached for, so this is the path of least surprise. Pillow (already
  a dep) encodes the bitmap to PNG. New helper `api/render.py::render_page1_png(data, ext)`
  returns `bytes | None` and **never raises** — any failure (bad bytes, encrypted, non-PDF)
  returns `None`.

- **Endpoint: `GET /scans/{scan_id}/files/{filename:path}/thumbnail`** in `routes/scans.py`,
  mirroring the owner-check of the sibling `/remediated` and `/content` routes
  (`core.store.get_scan(sid, owner=_owner(request))` → 404 on mismatch, which also avoids
  leaking scan existence). Flow: **blob cache hit → serve; miss → resolve source bytes →
  render → cache to blob → serve; any failure → 404** (never 500). A `?fresh=1` query bypasses
  the cache read for a forced re-render.

- **Source bytes** are resolved the same way the existing routes already do it, in order:
  the remediated blob copy if one exists (ADR 0010), else the local corpus file for a
  `source=local` scan (`ACP_LOCAL_CORPUS` / `test-corpus/files`), else the Drive original via
  the stored `drive_file_id` + a live `x-drive-token`. Whichever yields bytes first wins;
  none available → 404.

- **Cache: reuse `api/blob.py`** (ADR 0010's non-goals explicitly bless a second use case
  reusing the seam without a new ADR — this is that use case). Rendered PNGs go in a
  **separate container** `ACP_BLOB_RENDER_CONTAINER` (default `thumbnails`), keyed
  `{owner}/{scan_id}/{filename}.png` — the same owner/scan/file scheme, kept out of the
  `remediated` container so a render is never mistaken for a remediated artifact. As with the
  rest of `blob.py`, it's a **no-op returning `None` when `ACP_BLOB_ACCOUNT` is unset** (local
  dev): the endpoint still renders on demand, it just doesn't persist between requests.

- **Frontend** consumes it through one `api.js` helper (`getFileThumbnail(scanId, file)`,
  the authenticated-blob-fetch pattern of `getFileContent`) and a small `<Thumbnail>` that
  **removes itself on any load error** — so a missing preview is invisible, never a broken
  image. `pdfReport.js` fetches the same PNG and embeds it via the existing `addImage`
  data-URL path (the mova-logo mechanism); if the fetch fails the certification PDF is
  produced exactly as before.

**Office (docx/pptx/xlsx) is out of scope for phase 1** and returns `None` → 404 → placeholder.
Rasterizing Office needs either LibreOffice headless (a heavy image add) or a render mode on
the existing .NET Office CLI (`engine/office`); both are follow-ons tracked against ADR 0012,
not blockers for shipping the PDF preview that covers the bulk of the corpus.

## Consequences

- **Non-blocking by construction.** No scan/remediate/report code path calls the renderer or
  the endpoint. The worst case for any document is "no thumbnail" — the reviewer sees the
  finding list exactly as today, the drawer hides the image, the PDF certifies without a
  preview. This is the property the whole design optimizes for.
- **No new system dependency and no copyleft.** `api/requirements.txt` gains one pinned pure
  wheel (`pypdfium2`); the Dockerfile is untouched. No GPL/AGPL enters the image.
- **Lazy, not eager.** The first view of a given file pays the render cost (~a few hundred ms
  for a PDF page plus the source fetch); every subsequent view is a blob read. Rendering in the
  request path is acceptable at demo scale and keeps the scan pipeline entirely unaware of
  thumbnails. If render latency ever bites, the same helper can be called from the remediation
  worker to warm the cache — an additive change, no redesign.
- **No schema change.** The cache is content-addressed by the existing `{owner}/{scan_id}/
  {filename}` key; nothing is written to `file_records`. (A future `thumb_url` column, if we
  ever want to record render provenance, would follow the additive `ALTER TABLE ... ADD COLUMN
  IF NOT EXISTS` pattern — not needed now.)
- **Cost.** One extra small object (~tens of KB PNG) per viewed file in a standard-tier
  container, same footprint class as ADR 0010; only files a human actually opens get rendered.
- **Verification.** `render_page1_png` is unit-testable against a real corpus PDF (a byte PNG
  with a valid signature out). The endpoint's owner-check and 404-not-500 failure modes are
  unit-testable. The end-to-end (render → cache → display) is validated live post-deploy.

## Non-goals
- Multi-page or full-document rendering — page 1 only; it's a *preview*, not a viewer.
- Before/after diffing — the seam is built so a second (remediated) render slots in later,
  but pairing them is a separate surface.
- Office rasterization in phase 1 (see Decision) — Proposed, tracked against ADR 0012.
- Client-side rendering via the frontend's `pdfjs-dist` — considered (it's already a dep) but
  it only helps the two React surfaces, not the server-generated certification PDF, and it
  can't render Office; a single server seam serves all three consumers uniformly.
