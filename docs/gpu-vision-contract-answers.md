# ACP — GPU / Vision Implementation: Production-Contract Answers

**Purpose:** Confirmed answers to the seven open technical questions before presenting the GPU/vision
implementation as a final production contract (UTSW hospital / PHI pilot).

**Verification basis:**
- Source code verified against `origin/main` @ `43cd78a` (working tree clean, equal to remote).
- Q6 additionally confirmed against the **live** production `/config` endpoint.
- Every claim below carries a `file:line` citation; gaps are flagged where a limit is *confirmed absent*, not merely unlocated.
- Prepared 2026-08-20.

---

## Q1 — Does the vision model draft alt text for every extracted image, or only when existing alt is missing/inadequate?

**Answer: Only when alt text is missing or inadequate.** Vision drafting is gated per-image on a
shared "does this still need alt?" predicate; it never runs on an image that already has usable alt.

- **Assessment never calls the vision model.** The SC 1.1.1 detectors are pure XML/structure parsing
  (`api/formats/{docx,pptx,xlsx}/detectors/non_text_content.py`, `api/formats/pdf/detectors/non_text_content.py`);
  none import `ai`. Vision runs **only during remediation**, only on the images the same predicate flags.
  Detector and remediator are deliberately pinned to one predicate so the re-scan credit gate can't fail
  silently (`tests/test_office_alt_parity.py`).
- **"Inadequate" is defined — and is asymmetric by format:**
  - **Office (docx/pptx/xlsx):** empty; generic auto-name (`img|image|picture|photo|graphic|grafik` +
    optional number/extension); or filename-as-alt (token ending in an image extension, or any value
    containing `/` or `\`). A value with internal whitespace is treated as a real phrase and left alone —
    so "too short" alone does **not** trigger. `api/formats/office/images.py:35-57`.
  - **PDF:** inadequate = **only** missing or whitespace-only `/Alt`. No filename/placeholder heuristic —
    a `/Alt` of `"image1.png"` or `"image"` counts as adequate and is left untouched.
    `api/formats/pdf/structure.py:49-62`. **This is a real per-format asymmetry to disclose.**

**Trigger sites:** Office `api/remediate_office.py:370, 538`; PDF `api/remediate_pdf.py:847, 901`.

---

## Q2 — Are decorative-image classification and chart interpretation included in the current SC 1.1.1 implementation?

### (a) Decorative classification — **Yes on Office; none on PDF.**
- Explicit decorative markers are honored on Office (detector + remediator): a marked-decorative image is
  treated as conforming and skipped — `api/formats/office/images.py:65-90`, skip at `api/remediate_office.py:396`.
- **Active decorative *inference*** (deciding an undescribed image *should* be marked decorative) exists for
  Office via `proposals.infer_decorative` (`api/proposals.py:315-336`) — signals: decorative filename,
  near-uniform pixel fill, extreme aspect ratio, hairline/icon size. Called at `api/remediate_office.py:440`.
  **Never auto-applied** — it emits a Low "Mark as decorative — no alt text needed" proposal for a human
  (`api/remediate_office.py:450-457`), and only when no faithful alt source exists.
- **PDF has no decorative classification at all.** Decorative PDF content is `/Artifact`, structurally
  outside the `/Figure` walk, so it is excluded by construction rather than classified.

### (b) Chart interpretation — **Yes: real chart *data*, deterministic (not a generic "image of a chart").**
- **Native charts** (a real chart part, not image bytes): `chart_data.describe_chart`
  (`api/chart_data.py:310-330`) composes an accurate sentence from the chart's parsed values — title,
  series names, actual high/low data points (e.g. "Highest is X at 42, lowest is Y at 3"). Written
  deterministically onto the chart's `descr` — "zero model risk" (comment `api/chart_data.py:340-343`).
  Applies to pptx/xlsx/docx.
- **xlsx chart rendered as an image** (no vision draft available): `xlsx_chart_context.draft_from_entries` /
  `chart_alt_draft` (`api/xlsx_chart_context.py:160-181`) composes a draft from the sheet's adjacent data
  table, offered as a proposal (`api/remediate_office.py:469-484`).

---

## Q3 — For scanned PDFs, is the vision model analyzing every page or only pages selected after raster/OCR detection?

**Answer: Neither — the vision model is called at most once, on page 1 only.** For an image-only /
untagged scanned PDF there is **no per-page captioning and no OCR/raster page-selection gate** — there is
a hard-coded page-1 bound.

- **Assessment (the scan) sends nothing to the vision model** for a scanned PDF.
- **Scanned-PDF detection is deterministic/structural, not vision:** `api/classify.py:48-69` counts embedded
  images over the first 10 pages and extracts text over the first 5 pages; `is_scanned` when
  `text_len < 40 * min(pages,5)`. A separate 1.4.5 advisory (`api/office_structure.py:1056`) uses char +
  image bounding boxes (no render, no OCR).
- **OCR exists but does not gate page selection** — `api/ocr.py` runs tesseract over embedded images for
  1.4.5/1.4.9 findings, and `ocr_text()` (`api/ocr.py:101`) *grounds* an alt proposal (decides auto-apply
  vs. human-defer), not which pages reach vision.
- **The only vision touch on an image-only scanned PDF** is the reading-order proposal
  `_propose_reading_order()` (`api/remediate_pdf.py:171`), hard-bounded to page 1
  (`png = _render_page_png(source_path, 1)`, `api/remediate_pdf.py:190`), and it is a **1.3.2 proposal a
  human confirms — never auto-applied.**
- Vision is always applied to a **rasterized full-page PNG** (pypdfium2), never to individual embedded
  image objects.

> ⚠️ **Contract note:** if the customer expects per-page captioning of scanned content, that does **not**
> exist in the current build. Net for an image-only scanned PDF: assessment = 0 vision calls;
> remediation = at most 1 vision call (page-1 reading order).

---

## Q4 — Does scanned-PDF vision support only assessment evidence, or can it also draft remediation artifacts?

**Answer: Assessment / human-proposal only. It cannot write alt text back into a scanned PDF.**

- The only code that writes `/Alt` into a PDF, `_fix_pdf_figure_alt` (`api/remediate_pdf.py:822`), returns
  immediately on any untagged PDF: `if "/StructTreeRoot" not in root: return [], 0`
  (`api/remediate_pdf.py:841-842`). A scanned PDF is untagged by definition
  (`api/capabilities.py:159-165`, `_looks_scanned`), so there are no `/Figure` elements to receive `/Alt`.
- Scanned-page vision that exists is proposal/finding only: `describe_reading_order` (1.3.2, `api/ai.py:997`)
  is "only ever a PROPOSAL a human confirms … never an auto-fix"; images-of-text (1.4.5) is OCR-based
  finding detection (`api/ocr.py`), not write-back.

> **Footnote for the contract:** this rests on "scanned ⇒ untagged." A PDF that were *both* scanned *and*
> tagged with `/Figure` elements lacking `/Alt` could engage the write path. For the ordinary scanned PDF
> (untagged, one image per page), vision is assessment evidence only.

---

## Q5 — Is HTML actually in the UTSW pilot scope, or merely supported by the engine?

**Answer: Engine-supported; not a committed pilot deliverable.**

- HTML is a first-class supported format: `SUPPORTED_FORMATS = ("docx","pdf","pptx","xlsx","html")`
  (`api/estate_inventory.py:62`) — discovered, assessed, and remediated like the others.
- The UTSW pilot is scoped **document-first (`.docx`)** (roadmap scope: *hospital · PHI · .docx-first*).
- **Recommended contract phrasing:** "HTML is supported by the platform; it is outside the committed
  pilot scope, which is document-first (.docx)."

---

## Q6 — Is `llama3.1:8b` deployed on the same T4 service in the proposed Azure configuration?

**Answer: Yes — confirmed on the live service.**

Live production `/config` (`ai` block = `ai.provenance()`, `api/routes/system.py:351`):

```json
{
  "provider": "ollama",
  "model": "llama3.1:8b",
  "vision_model": "llava:13b",
  "zone": "cloud",
  "host": "acp-ollama-gpu.purplebeach-80e1296b.westus2.azurecontainerapps.io"
}
```

- **`llama3.1:8b` (text) and `llava:13b` (vision) are both resident on the same `acp-ollama-gpu` T4
  service** today. The T4's 16 GB holds both.
- **Region caveat:** it currently reads `zone: "cloud"` because the GPU is in **West US 2** while the app
  is in **East US 2** (cross-region). The proposed East US 2 co-location keeps the *same two models on the
  same T4 SKU* and flips the governance zone to `local`.
- ⚠️ **Do not cite `deploy/gpu/pull_models.sh`** for the deployed model set — it is a stale RunPod-era
  script (pulls `llava:7b` / `llama3.2-vision:11b` / `bakllava`). The authoritative source is the live
  `/config` above. (Code defaults in `api/ai.py` are `llama3.2` text / `moondream` vision — the CPU/keyless
  fallback, overridden by deploy env.)

---

## Q7 — What are the page, image-size, and timeout limits used to control GPU cost and queue latency?

### Page limits
| Control | Value | Override | Location |
|---|---|---|---|
| Scanned/untagged reading-order → vision | **page 1 only** | none (hard-coded) | `api/remediate_pdf.py:190` |
| Tagged figure-alt vision calls per PDF | **25** (`_VISION_MAX_FIGURES`) | none | `api/remediate_pdf.py:29` |
| `is_scanned` classify peek | 10 pages (images) / 5 (text) | none | `api/classify.py:57,64` |
| 1.4.5 structural scanned-page check | **20** (`_MAX_PAGES_SCANNED`) | none | `api/office_structure.py:1051` |
| OCR images-of-text per file | **30** (`_MAX_IMAGES`) | `ACP_OCR_MAX_IMAGES` | `api/ocr.py:45` |

There is **no global "max pages rasterized/analyzed per PDF" cap** beyond these.

### Image-size limits
- **No resize/downscale of the image before the vision call, and no max-dimension or byte cap on vision
  input.** Every provider base64-encodes `image_bytes` verbatim (`api/providers.py:186-190, 337, 407, 476,
  553-558`). **Confirmed absent — a real cost/latency gap.**
- PDF page render sent to vision: **150 DPI** (`_RENDER_SCALE = 150/72`, `api/remediate_pdf.py:32`), **no
  long-edge cap** (`_render_page_png`, `api/remediate_pdf.py:995-1014`). A letter page ≈ 1275×1650 px is
  sent at full resolution.
- (Non-vision paths, for reference) preview thumbnails downscale to 1000 px long edge (`api/render.py:23`);
  OCR input downscales to 3000 px long edge (`api/ocr.py:46`).

### Timeout limits (`api/ai.py`, all env-overridable unless noted)
| Env var | Default | Purpose | Line |
|---|---|---|---|
| `OLLAMA_VISION_TIMEOUT` | **120.0 s** | vision inference; also reading-order & cloud-escalation | `api/ai.py:40` |
| `RUNPOD_VISION_TIMEOUT` | **240.0 s** | vision when provider is `runpod_serverless` (cold-boot) | `api/ai.py:45` |
| `OLLAMA_PROBE_TIMEOUT` | **3.0 s** | fast availability probe (`/api/tags`) | `api/ai.py:49` |
| `OLLAMA_COLD_START_TIMEOUT` | **90.0 s** | retry probe budget (scale-from-zero) | `api/ai.py:50` |
| `OLLAMA_PROBE_TTL` | **300.0 s** | memoise probe so cold Ollama isn't re-probed per file | `api/ai.py:53` |
| (hard-coded) text explain | **90 s** | `/api/generate` text explanation | `api/ai.py:259` |
| `ACP_OFFICE_RENDER_TIMEOUT` | **60 s** | LibreOffice Office→PDF convert (render only) | `api/render.py:88` |

- **No per-file / per-request overall wall-clock cap on vision.** Worst case for a tagged PDF is
  (per-call timeout) × (≤25 calls), run **sequentially** within one document.
- Generation caps (token count, not time): vision **128** tokens (`api/providers.py:190`), reading-order
  **140** (`api/ai.py:1021`), text **120** (`api/ai.py:255`).

### Concurrency / batching
- `ACP_WORKERS` — in-process worker threads, default **0** (opt-in), safety cap **16** (`api/core.py:493,496`).
- Assessment fan-out pool: `min(8, cpu*2)` (`api/scanner.py:18`).
- These bound **documents in flight**, not vision calls within a document (which are sequential).

---

## ⚠️ Gaps to flag before signing

1. **No image downscaling before the vision call, and no cap on the 150-DPI page render.** The T4 receives
   a full-resolution page PNG each time — the largest uncontrolled GPU-cost/latency variable. *Confirmed
   absent.*
2. **Scanned PDFs get page-1 vision only** — no per-page captioning of scanned content exists.
3. **PDF alt-adequacy is weaker than Office** (no placeholder/filename heuristic) and **PDF has no
   decorative classification** — a PDF-heavy estate gets a lighter 1.1.1 pass than a `.docx` estate.
4. **No per-file wall-clock cap on vision** — worst case is 25 sequential calls × the per-call timeout.
5. **HTML is out of the committed pilot scope** though the engine supports it — state as capability, not
   commitment.

---

*All source citations verified against `origin/main` @ `43cd78a`; live model confirmed via production
`/config`. Where a limit is described as absent, that was confirmed by exhaustive search, not merely
not-found.*
