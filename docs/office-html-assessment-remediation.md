# Office (Word/PowerPoint/Excel) & HTML — assessment & remediation architecture

**Audience:** engineering + product. **Companion to** `docs/pdf-assessment-remediation.md` — same
file-grounded treatment for the non-PDF formats. Verified against `main` on 2026-08-14. Where something
is absent or explicitly blocked, this says so.

---

## TL;DR

- **Two engines per document type, plus a supplement layer.** DOCX/PPTX/XLSX are assessed by a **.NET
  analyser run as an out-of-process subprocess** (`DocumentFormat.OpenXml`), *plus* first-party Python
  checks (`api/office_structure.py`) that fill coverage the partner engine doesn't reach. PDF is
  in-process Python; **Office is a subprocess** — the key architectural difference.
- **Office remediation is raw OOXML** — `zipfile` + `lxml`/`ElementTree` + regex. There is **no
  python-docx / python-pptx / openpyxl** anywhere in `api/`.
- **HTML is assess *and* remediate**, both in-process Python via **lxml** (`_analyse_html` +
  `remediate_html`). A separate **axe-core@4.9.1 + Playwright** analyser exists under the PDF/worker
  engine but the control-plane scanner does **not** call it.
- Nearly every criterion has an auto or assisted lane; the only intentional document human-only lanes
  are **pptx 2.1.1** (keyboard — a runtime property, not in the file) and **xlsx 3.1.2** (no element to
  write into).

---

## 1. Engine split (the one table to remember)

| Format | Assessment engine | Process model | Assess? | Remediate? | Core libraries |
|---|---|---|---|---|---|
| **DOCX** | .NET `AcpScan.Cli` (`.net/office`) + `office_structure.py` | **out-of-process subprocess** + in-proc Python | ✅ | ✅ | DocumentFormat.OpenXml 3.5.1 (.NET); zipfile/lxml/ElementTree (Py) |
| **PPTX** | same | same | ✅ | ✅ (2.1.1 human-only) | same |
| **XLSX** | same | same | ✅ | ✅ (3.1.2 human-only) | same |
| **HTML** (control plane) | `scanner._analyse_html` (`python/html`) | in-process Python | ✅ | ✅ (`remediate_html`) | lxml 6.1.1 |
| **HTML** (worker engine, *not* wired to scanner) | `engine/…/html_analyser.py` | out-of-process browser | ✅ | ✗ | axe-core 4.9.1 + Playwright Chromium |
| **PDF** (for contrast) | in-proc Python `PdfAnalyser` (`python/pdf`) | in-process | ✅ | ✅ | pikepdf/pypdf/pdfplumber (see the PDF doc) |

Python control-plane deps (`api/requirements.txt`): fastapi 0.137.1, **lxml 6.1.1**, pikepdf 10.8.0,
pypdf 6.14.2, pdfplumber 0.11.10, pillow 12.2.0, pytesseract 0.3.13, langdetect 1.0.9, reportlab 4.5.1.
AI is local (Ollama) — no Anthropic/OpenAI SDK.

---

## 2. The .NET Office analyser

**Location:** `engine/office-analysers/` — `DigitalA11y.Analysers.DotNet/` (the analysers) and
`DigitalA11y.Core/` (shared manifest models, rule-id/metadata registries). Target framework **net10.0**.

**Libraries:**
- **`DocumentFormat.OpenXml` 3.5.1** — the sole OOXML parser (centrally pinned in
  `Directory.Packages.props`; the analyser `.csproj` carries no inline version).
- `Microsoft.Extensions.DependencyInjection.Abstractions` / `Options` 10.0.8 (DI plumbing).

**Orchestration:** each format has an analyser class (`DocxAnalyser` / `PptxAnalyser` / `XlsxAnalyser`)
that opens the file with OpenXml (`WordprocessingDocument.Open` etc.), iterates DI-registered
`IDocxRule` / `IPptxRule` / `IXlsxRule` rules, and catches per-rule exceptions into `AnalyserError`.
Contrast is a real computation (`Helpers/ColourContrastHelper.cs` + `AltTextHeuristics.cs`), with a
`SkipColourContrast` option.

### DOCX rules (`Docx/Rules/`)
| Rule | SC | Detection |
|---|---|---|
| `AltTextRule` | 1.1.1 | `descr=` missing/empty on image `wp:docPr` |
| `TableHeaderRule` | 1.3.1 | table with no marked header row |
| `HeadingStructureRule` | 1.3.1 | heading outline problems |
| `ColourContrastRule` | 1.4.3 | run fg vs bg < 4.5:1 (worst run per paragraph) |
| `DocumentTitleRule` | 2.4.2 | no title in core props |
| `BookmarksRule` | 2.4.2 | navigation/bookmark concerns |
| `LinkPurposeRule` | 2.4.4 | vague / raw-URL link text (kept in sync with the Python `_is_vague_link_text`) |
| `DocumentLanguageRule` | 3.1.1 | no default/run-level language |
| `LanguageOfPartsRule` | 3.1.2 | a 20+ word run in a *different Unicode script* than the body, no `w:lang` |

### PPTX rules (`Pptx/Rules/`)
`AltTextRule` (1.1.1), `TableHeaderRule` (1.3.1), `ReadingOrderRule` (1.3.2, z-order), `ColourContrastRule`
(1.4.3), `AnimationOrderRule` (2.1.1), `SlideTitleRule` (2.4.2), `SlideTitleUniquenessRule` (2.4.2),
`LinkPurposeRule` (2.4.4), `DocumentLanguageRule` (3.1.1).

### XLSX rules (`Xlsx/Rules/`)
`AltTextRule` (1.1.1), `TableHeaderRule` (1.3.1), `MergedCellsRule` (1.3.2), `HiddenContentRule` (1.3.2,
hidden data), `BlankWorksheetRule` (1.3.2), `DocumentTitleRule` (2.4.2), `TableNameRule` (2.4.2, generic
table name), `SheetNameRule` (2.4.6, default `Sheet1…`), `SheetNameUniquenessRule` (2.4.6), `LinkPurposeRule`
(2.4.4, incl. `=HYPERLINK()`), `DocumentLanguageRule` (3.1.1).

**CLI:** `spike/dotnet/AcpScan.Cli/` (`OutputType=Exe`, net10.0) → built DLL
`spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll`. Usage `AcpScan.Cli <inputDir> <outJson>`.
It walks every `.docx/.pptx/.xlsx` in the dir and writes a **JSON array manifest** — one object per file
`{ file, succeeded, errors, issues[] }`, each issue `{ ruleId, wcag, severity, title, location{…} }`.
Extensive per-file try/catch means one bad file no longer aborts the batch (the historical
"office CLI exited -6 / SIGABRT" bug); it exits 0 and records failures as data.

---

## 3. How the .NET engine is invoked from Python

`api/scanner.py::_analyse_office(dest)`:
- Resolves `DOTNET = ACP_DOTNET or which("dotnet")` and `CLI_DLL = ACP_OFFICE_CLI or …/AcpScan.Cli.dll`.
- **`subprocess.run([DOTNET, CLI_DLL, dest, out], capture_output=True, timeout=ACP_OFFICE_CLI_TIMEOUT|180s)`**
  over a one-file temp dir, then `json.loads(out)` and maps each file's `{succeeded, issues, errors}` into
  the internal shape. Non-zero exit → findings kept but every file gets a process-level error → rubric
  marks the file **uncertain** (score is an upper bound, not certifiable). Missing/bad JSON → engine-error.
- Dispatch: `raw = {"engine": ".net/office", **office.get(name, …)}`.

**Contrast with PDF:** `_analyse_pdf` is an **in-process import** (`sys.path.insert` → `from
analysers.pdf_analyser import PdfAnalyser`). So **Office = out-of-process .NET subprocess; PDF = in-process
Python module.** HTML is also in-process Python.

---

## 4. First-party Python Office checks — `api/office_structure.py`

Supplements the .NET engine for coverage it doesn't reach. **All `zipfile` + `ElementTree`/regex — no
python-docx/pptx/openpyxl.** Dispatched via `checks_for(path, ext)`; `_finding()` = hard findings,
`_review_finding()` = advisory `severity:REVIEW` with structured evidence.

- **DOCX:** heading skip/empty/pseudo (2.4.6/1.3.1), link purpose across body + header/footer/endnotes
  (2.4.4/2.4.9), form-field labels (3.3.2, + delegates 4.1.2 to `formats/docx/detectors/name_role_value.py`),
  section headings (2.4.10), justified text (1.4.8), reading-order risk (1.3.2), non-text contrast (1.4.11 REVIEW).
- **PPTX:** empty title (2.4.6), low contrast AA/AAA (1.4.3/1.4.6), **audio autoplay (1.4.2)** —
  `pptx_audio_autoplay_checks`, one finding per slide with a zero-delay `<p:timing>` trigger and no onClick
  gate — plus focus-order, resize-text, complex-bg contrast, non-text contrast (1.4.11 REVIEW). *Note:*
  distinguishing autoplay vs click-triggered **complex** media is explicitly **not attempted** (blocked, not
  deferred) — only the narrow zero-delay case is implemented.
- **XLSX:** low contrast AA/AAA (1.4.3/1.4.6, font vs fill resolved through the theme + tint formula),
  default labels (2.4.6), non-text contrast (1.4.11 REVIEW).
- **Format-agnostic Office supplements:** control review (2.1.2/4.1.2 REVIEW), colour-only (1.4.1), reflow
  (1.4.10), text spacing (1.4.12), non-text content (1.1.1).

Related: **`api/geometry.py::shape_bbox`** computes OOXML shape geometry (pptx/xlsx anchors → px box) for
review-UI overlays (zipfile + ElementTree; Office-only — no PDF branch). **`api/apply_alt.py`** writes
approved alt back by rewriting `descr=` (or marking decorative) and repacking the zip — again raw OOXML.

---

## 5. Office remediation — `api/remediate_office.py`

Entry `remediate_office(path, *, lang, ai_enabled, …)`. **All writes are direct OOXML** — `zipfile` +
`ElementTree` + **`lxml.etree`** + regex. **No python-docx/pptx/openpyxl.**

- **DOCX** `_remediate_docx_structure` — pseudo-heading promotion + table `firstRow` + single H1 (1.3.1),
  contrast recolour (1.4.3), core-props title/language (2.4.2/3.1.1), form-field/content-control name via
  `w:alias` (4.1.2/3.3.2). Assisted drafts via `_draft_docx_assisted`.
- **PPTX** `_remediate_pptx_slides` — add title (2.4.2), mark table headers (1.3.1), contrast recolour
  (1.4.3/1.4.6), shape reorder (1.3.2), language (3.1.1).
- **XLSX** `_remediate_xlsx_contrast` + `_remediate_xlsx_structure` — defined-table `headerRowCount`
  (1.3.1), un-hide data rows/cols (1.3.2), font-clone recolour (1.4.3/1.4.6), title/language.
- Alt text for all three via `apply_alt.py`; approved values written back by `apply_field_name.py` /
  `apply_link_text.py` / `apply_text_values.py`. (Office fixers are functions in `remediate_office.py`, not a
  `fixers/` package — that package exists only under the PDF engine.)

**Auto / assisted / human per format:**
- **DOCX** — richest auto lane (1.3.1, 1.4.3, 2.4.2, 2.4.6, 3.1.1, 3.3.2, 4.1.2); most of the rest assisted;
  **no pure-human doc lane**.
- **PPTX** — auto (1.3.1, 1.3.2, 1.4.3, 1.4.6, 2.4.2, 3.1.1); assisted alt/media/link/language; **human-only:
  2.1.1** (keyboard is a *runtime* property, not in the file — the single intentional document human lane).
- **XLSX** — auto (1.3.1, 1.3.2, 1.4.3, 1.4.6, 2.4.2, 3.1.1); assisted (1.1.1/1.4.5/2.4.4/2.4.6/3.1.5);
  **human-only: 3.1.2** (declared permanent gap — "the format has no element to write into";
  `apply_text_values` refuses xlsx for this mode).

---

## 6. HTML — assess **and** remediate (two analysers exist; the scanner uses the lxml one)

**(a) Control-plane analyser — the one the scanner actually runs.** `scanner._analyse_html` (engine tag
`python/html`), a hand-written **lxml** rule set (~40 `HTML_*` findings), in-process Python — **not axe-core,
not Node.** Coverage spans 1.1.1, the **1.2.x media track detection** (`<video>`/`<audio>` caption/description/
transcript tracks → `HTML_VIDEO_NO_CAPTIONS` / `HTML_VIDEO_NO_DESCRIPTION` / `HTML_AUDIO_NO_TRANSCRIPT`),
1.3.x, 1.4.x, 2.4.x, 2.5.3/2.5.8, 3.1.1/3.3.2, 4.1.2 (predicates mirror `frontend/src/rules/wcag-*.js`).
**HTML remediation exists** — `api/remediate.py::remediate_html` (deterministic lxml-tree fixers: `_fix_lang`,
`_fix_title`, `_fix_contrast`, `_fix_autoplay`, `_fix_bypass_blocks`, `_fix_use_of_color`, `_fix_focus_order`,
`_fix_input_purpose`, `_fix_reflow`, `_fix_text_spacing`, …).

**(b) A separate axe-core engine the scanner does NOT wire.** `engine/pdf-analyser/analysers/html_analyser.py`
injects **axe-core@4.9.1** (pinned CDN) into a **Playwright Chromium** browser and maps violations →
`A11yIssue`. It belongs to the worker/pdf-analyser engine and is **not** called by `api/scanner.py`. Worth
knowing both exist; the control plane uses the lxml one.

---

## 7. Capability coverage — `api/remediation_capability.py`

Three lanes: **auto** (⚡ deterministic, re-scan verified) / **assisted** (🤖 AI/OCR prefilled, one-click
approval) / **human** (👤 re-authoring).

- **docx:** auto = 1.3.1, 1.4.3, 2.4.2, 2.4.6, 3.1.1, 3.3.2, 4.1.2 · assisted = 1.1.1, 1.3.2, 1.3.3, 1.4.1,
  1.4.5, 1.4.8, 1.4.9, 1.4.11, 2.4.4, 2.4.9, 2.4.10, 3.1.2, 3.1.5 · human = 2.1.2.
- **pptx:** auto = 1.3.1, 1.3.2, 1.4.3, 1.4.6, 2.4.2, 3.1.1 · assisted = 1.1.1, 1.4.2, 1.3.3, 1.4.5, 1.4.9,
  2.4.4, 2.4.6, 2.4.9, 3.1.2, 3.1.5 · **human = 2.1.1**.
- **xlsx:** auto = 1.3.1, 1.3.2, 1.4.3, 1.4.6, 2.4.2, 3.1.1 · assisted = 1.1.1, 1.3.3, 1.4.5, 1.4.9, 2.4.4,
  2.4.6, 3.1.5 · **human = 3.1.2**.
- **html:** broad auto set (1.3.1, 1.3.4, 1.3.5, 1.4.1–1.4.4/1.4.6/1.4.10/1.4.12, 2.4.1/2.4.2/2.4.3/2.4.6/
  2.4.7, 2.5.3, 3.1.1/3.1.4, 3.3.2, 4.1.2 — several clear incidentally) · assisted = 1.3.3, 2.4.4, 3.1.2, 3.1.5.
  **Declared not-ready / human:** 1.1.1 (no HTML alt proposer — external image bytes), **1.2.1/1.2.2/1.2.3**
  (media transcript/captions/description — see the multimedia LOE), 1.3.2 (CSS visual reorder), 1.4.5
  (image-of-text), 1.4.11 (non-text contrast), 2.4.9, 2.5.8 (target size).

**Assessment-axis overrides** (`ASSESSMENT_OVERRIDES`) — where an auto-remediable cell must *not* read as
certifiable: `(pptx,2.1.1)`→human, `(docx,2.4.6)`/`(html,2.4.6)`→review (heading well-formedness ≠
descriptive headings), `(docx,4.1.2)`→review (content-control-only detector, coverage PARTIAL). These encode
the honest "auto-remediable ≠ certifiable" gaps.

---

## What exists vs. not built

- **Fully built & auto (per format above)** — structure, contrast, title, language, headers, form/field
  names — all re-scan verified.
- **Assisted (AI/OCR proposes, human approves)** — alt text, link purpose, language-of-parts, images-of-text.
- **Intentional human-only:** pptx 2.1.1 (keyboard, runtime), xlsx 3.1.2 (no element to write), docx 2.1.2.
- **HTML media (1.2.x)** — detected (track presence) but transcript/caption/description generation is **not
  built** (no ASR pipeline; see `docs/loe-multimedia-captioning.md`).
- **Not present:** python-docx / python-pptx / openpyxl (Office is raw OOXML); the axe-core+Playwright HTML
  engine is not wired into the control-plane scanner.
