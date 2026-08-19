# PDF accessibility — assessment & remediation architecture

**Audience:** engineering + product. **Scope:** how ACP assesses and remediates PDF accessibility.
**Grounding:** every claim below names the file/function it comes from; where something is *not*
built, this says so. Verified against `main` on 2026-08-14.

---

## TL;DR

- PDF findings come from **three** code layers merged per file — not one engine.
- The PDF engine runs **in-process (Python import)**, unlike the Office engine (a .NET subprocess).
- Libraries: **pikepdf** + **pdfplumber** (structure/layout), **pypdf** (metadata write), **pypdfium2**
  (rasterize for render-verified contrast + thumbnails), **pytesseract/tesseract** (OCR), local
  **Ollama** llava-class model (OCR-grounded alt-text). No PyMuPDF/fitz (AGPL avoided), no poppler,
  no cloud OCR/LLM.
- Auto-fixable today: language, title/DisplayDocTitle, bookmarks, focus-order `/Tabs`, **contrast
  recolour (1.4.3/1.4.6)**, AcroForm names. Assisted (AI proposes, human approves): figure alt,
  reading order, structure/heading maps, images-of-text. Human-only: link purpose (no write-back),
  proper re-tagging, table `/TH`.

---

## 1. Assessment — three detection layers

PDF analysis is not a single engine. Three code locations each contribute findings, which
`scanner.analyse_and_assess` merges and de-duplicates per file.

### Layer A — `engine/pdf-analyser/` (the vendored "worker-python" analyser)
The deploy log's *"vendored Python PDF analyser, 41 modules, /app/engine/worker-python"* is this
directory (exactly 41 `.py` files; the "worker-python" name survives only in comments and the
`ACP_PDF_ENGINE` env var). `scanner.py` resolves it at runtime:
`WP = Path(os.environ.get("ACP_PDF_ENGINE") or (ACP/"engine"/"pdf-analyser"))`.

- **Orchestrator:** `analysers/pdf_analyser.py` — `class PdfAnalyser`, opens the file with
  `pikepdf.open()` **and** `pdfplumber.open()`, runs a fixed `_RULES` list on a thread executor.
- **Rule protocol:** `IPdfRule.check(pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF)`.

The 8 structural rules (`analysers/rules/pdf/`):

| Rule file | `rule_id` | WCAG | How it detects | Remediation |
|---|---|---|---|---|
| `tagged_pdf.py` | `pdf.tagged` | 1.3.1 | `/MarkInfo /Marked` true **and** `/StructTreeRoot` present | human |
| `document_title.py` | `pdf.document-title` | 2.4.2 | `docinfo['/Title']` non-empty | auto |
| `display_title.py` | `pdf.display-doc-title` | 2.4.2 | `/ViewerPreferences /DisplayDocTitle` == true | auto |
| `document_language.py` | `pdf.document-language` | 3.1.1 | catalog `/Lang` non-empty | auto |
| `image_alt_text.py` | `pdf.missing-alt-text` | 1.1.1 | StructTree `/Figure` nodes lacking `/Alt` | assisted |
| `table_headers.py` | `pdf.table-headers` | 1.3.1 | StructTree `/Table` with no `/TH` descendant | human |
| `reading_order.py` | `pdf.reading-order` | 1.3.2 | pdfplumber visual order vs stream order, ≥25% divergence over first 20 pages | assisted |
| `bookmarks.py` | `pdf.missing-bookmarks` | 2.4.2 | PDFs ≥10 pages must have `/Outlines /First` | auto |

Layer A covers **1.1.1, 1.3.1, 1.3.2, 2.4.2, 3.1.1**. It does **not** do contrast, use-of-color, or OCR.

### Layer B — `api/office_structure.py` (first-party measurement checks)
Dispatched via `checks_for(path, ".pdf")`. Each check "never raises" (advisory unless a real
measurement is made):

- `pdf_contrast_checks` — **1.4.3 / 1.4.6**. Real per-glyph WCAG ratio: `non_stroking_color`
  foreground vs the background structurally resolved *behind each glyph*. The shared traversal
  `_pdf_contrast_scan` also feeds the fixer's recolour plan, so finding and fix agree.
- `pdf_nontext_contrast_checks` — **1.4.11** (bordered-rect outline-on-fill).
- `pdf_text_over_image_checks` — glyphs over an image (contrast unresolvable structurally) → paired
  with render-verify below.
- `pdf_text_spacing_checks` — **1.4.12** (line-pitch < 1.15× font).
- `pdf_use_of_color_checks` — **1.4.1** (colour-only-distinguished hyperlink).
- `pdf_scanned_page_checks` — **1.4.5 (Review)** cheap pre-OCR heuristic (near-zero chars + a
  page-covering image ⇒ likely scan); runs even when OCR is off.
- `pdf_non_text_content_checks` — **1.1.1**, delegates to `formats/pdf/detectors/non_text_content.py`
  (the first-party twin of Layer A's alt-text rule, so the in-process re-scan can observe 1.1.1).
- Plus bypass-blocks, form-field, headings/labels, link-purpose, focus-order checks.
- `formats/pdf/detectors/name_role_value.py` — **4.1.2**, walks **AcroForm terminal fields only**
  (this is why 4.1.2 assessment is capped at review — see §3).

**Render-verified measurement** — `api/pdf_render_verify.py::measure_pdf_over_image_contrast` rasterizes
via **pypdfium2** (`api/render.py::render_page_png`, 144 DPI) to measure contrast where structural
analysis can't (text over image). ADRs `0025`, `0027`.

### Layer C — `api/ocr.py` + `api/formats/pdf/detectors/`
OCR and structural detectors for images-of-text, focus order, and name/role/value (see §4 OCR).

---

## 2. Remediation — `api/remediate_pdf.py`

Entry point `remediate_pdf(path, *, lang, ai_enabled, scan_id, diffs, proposals, applied_fixes,
in_scope)`. **Two-stage write:**
1. **pikepdf** — catalog/structural fixes + figure alt + content-stream recolour → `.mid-` file.
2. **pypdf** (`PdfWriter(clone_from=...)` + `add_metadata`) — docinfo `/Title` + provenance stamp →
   `remediated-<name>.pdf`. (pypdf is used for metadata deliberately: pikepdf's docinfo writes persist
   nondeterministically once libxml2 is loaded in the same long-lived worker.)

### Fully automatic (deterministic + re-scan verified)
| SC | What | Where |
|---|---|---|
| 3.1.1 | catalog `/Lang` | `PdfLanguageFixer` |
| 2.4.2 | `/Title` + `DisplayDocTitle` | `PdfDisplayTitleFixer` + pypdf metadata |
| 2.4.1 | bookmark outline from detected headings | `_generate_pdf_outline` |
| 2.4.3 | focus order (`/Tabs = /S` on pages with widgets) | `remediate_pdf` |
| 1.4.3 / 1.4.6 | text contrast recolour | `_fix_pdf_text_contrast` (see §2.1) |
| 4.1.2 | AcroForm accessible name (`/TU` from a meaningful `/T`) | `_fix_pdf_form_fields` |

### Assisted (AI/OCR proposes a value; a human approves; never silently applied)
- **1.1.1** figure alt — `_fix_pdf_figure_alt` renders the page (150 DPI, max 25 figures) and captions
  via the local vision model **only when grounded in OCR text**; else defers to a review card with the
  page render. Applied by `apply_pdf_figure_alt`.
- **1.3.2** reading order — `_propose_reading_order`.
- **1.3.1** structure map — `_propose_structure_map` (heading hierarchy).
- **2.4.6** headings — `_propose_pdf_headings` (font-hierarchy map, tagged PDFs).

### Detect-only → routed to a human (no write path exists)
- **2.4.4** link purpose — **explain-only**: a label is derivable from the target, but *there is no
  PDF link write-back*, so it routes to a human and is never auto-proposed.
- **1.3.1** proper re-tagging (structure-tree authoring).
- Table `/TH` headers.

### 2.1 The 1.4.3 contrast fixer and the dark-theme incident
`_fix_pdf_text_contrast(pdf)` is a deterministic content-stream rewrite (pikepdf), gated entirely on
`office_structure.pdf_contrast_recolor_plan(pdf_bytes)`. The incident, documented in the code:

> an earlier white-background-assuming model darkened white-on-black cover text from a passing **21:1
> to a 3.66:1 AA FAILURE, silently**.

The current fixer recolours a glyph **only** where it is *measured* to fail against its own
structurally-resolved background, **only** toward a colour proved to clear *every* background it is
painted on (`_pdf_recolor_for_all` abstains → glyph untouched when it sits over an image, straddles a
fill edge, or shares a colour across light and dark panels), and **only** for text fill operators
(`_colours_text()`; shapes/backgrounds/images are never rewritten). The post-fix re-scan is the credit
gate — an unproven fix is never claimed. White-on-dark text at 21:1 is now left alone.

---

## 3. Capability declaration

**Backend source of truth:** `api/remediation_capability.py` — `REMEDIATION["pdf"]`, two axes (ADR
0023). The remediation lane (auto/assisted/human) is authored + round-trip proven; the assessment lane
(🟢/🟡/🔴) is *derived* with audited `ASSESSMENT_OVERRIDES`. **Frontend mirror:**
`frontend/src/capability.js::CAPABILITY_FALLBACK["pdf"]` (offline fallback for `GET /capability`).

Key declared gaps:
- **4.1.2** is auto-fixable for AcroForm names but its *assessment* is held at **review** because the
  detector walks AcroForm terminal fields only — no StructTreeRoot walker yet (explicit TODO,
  `remediation_capability.py`: "delete this line when a tag-tree detector lands").
- **2.4.4** is **human-only** (no link write-back).
- No table-`/TH` auto-fix and no proper re-tagging fix.

---

## 4. OCR / image-based PDFs — `api/ocr.py`

- **Engine:** tesseract via **pytesseract** (`pytesseract==0.3.13`; wraps the local tesseract binary,
  installed in the Dockerfile). No cloud OCR. Alt-text captioning uses a **local llava-class Ollama**
  vision model, but only *grounded* in OCR text.
- **Self-gating:** `is_available()` checks the `ACP_DETECT_IMAGES_OF_TEXT` env + that
  `pytesseract.get_tesseract_version()` succeeds. If the binary is missing it warns once and 1.1.1
  alt-text **downgrades from applied to proposed** rather than failing (documents the 2026-08-08
  lost-day incident).
- **Image extraction:** `_pdf_images` uses pikepdf `PdfImage(obj).as_pil_image()`; bounded at 30/file
  (truncation surfaced as `OCR_IMAGE_CAP_REACHED`).
- **1.4.5** `images_of_text` — OCR each image; ≥10 real words ⇒ `OCR_IMAGE_OF_TEXT`; charts exempted
  (`_looks_like_chart`). **1.4.9** `images_of_text_no_exception` — stricter AAA floor (≥3 words, no
  chart exception).
- **Grounds 1.1.1:** `ocr_text(img_bytes)` is the grounding source — a caption auto-applies only when
  anchored in the image's own OCR'd text; a textless photo stays a human-confirmed vision guess. (This
  is exactly why the live vision path degrades to a template when the vision model isn't producing
  image-derived text.)

---

## 5. Frontend

- **Preview:** `frontend/src/PdfPreview.jsx` lazy-loads **pdfjs-dist `^6.0.227`**, renders the first
  ~2 pages to canvas; falls back to an "Open the document ↗" link on error.
- **Evidence thumbnails/geometry are server-side**, not from pdfjs: `remediate_pdf._render_page_png`
  (pypdfium2) produces page thumbnails (320px review / 96px receipt), base64-stored in
  `hitl_queue.proposals` / `applied_fixes`. `api/geometry.py::shape_bbox` is **Office-only** — it has
  no PDF branch; PDF geometry comes from pdfplumber bboxes + rendered PNGs.
- **Client-side demo:** `pdfAudit.js` (pdf-lib) checks title/`/Lang`/`StructTreeRoot` in-browser and
  writes a downloadable title+language fix; tagging/reading-order is detected-and-flagged only.

---

## 6. Pipeline placement

Flow: **scan_discover → scan_file → assess → remediate**, all in `api/scanner.py`.

- **Assess one file:** `analyse_and_assess(tmp, name, ...)` — for `.pdf` sets
  `raw = {"engine": "python/pdf", **_analyse_pdf(...)}` (Layer A), then **appends** first-party findings:
  OCR (`ocr.images_of_text` + `images_of_text_no_exception`), text/lang
  (`textchecks.content_findings` + `office_structure.language_marked_spans`), and structural
  (`office_structure.checks_for(...)` = Layer B). Then `_collapse_duplicate_alt(_collapse_reading_order(...))`
  de-dupes across layers. Scoring via `Rubric.assess(...)` over in-scope findings.
- **`_analyse_pdf(path)`** is an **in-process import**: `sys.path.insert(0, str(WP))` then
  `from analysers.pdf_analyser import PdfAnalyser` and `asyncio.run(PdfAnalyser().analyse(...))`. If the
  engine can't import, it returns a structured error naming the cause — never a fabricated pass.
  (Contrast: the Office analyser *is* a subprocess — `subprocess.run([DOTNET, CLI_DLL, ...])`.)
- **Remediate:** `api/remediate.py` calls `remediate_pdf.remediate_pdf(...)`, threads
  `proposals`/`applied_fixes`/`in_scope`; deferred items become HITL review cards; the post-fix re-scan
  (first-party checks only) is the credit gate that proves an auto fix cleared.

---

## What exists vs. not built

- **Built & auto:** language, title + DisplayDocTitle, bookmarks, focus-order `/Tabs`, contrast
  recolour (1.4.3/1.4.6), AcroForm `/TU` names — all re-scan verified.
- **Built as assisted:** figure alt (OCR-grounded vision), reading order, structure/heading maps,
  images-of-text OCR, language-of-parts.
- **Declared but not auto-certifiable:** 4.1.2 (AcroForm-only detector; StructTreeRoot walker is a TODO).
- **Detect-and-route-to-human only:** 2.4.4 link purpose, proper re-tagging, table `/TH`.
- **Not present:** PyMuPDF/fitz, poppler, cloud OCR/LLM; `api/geometry.py` has no PDF branch.
