# ADR 0034 — A tagged, accessible conformance-report PDF (renderer migration)

**Status:** Proposed. Renderer selected; POC passed the structural detector; a bounded spike has run
(`spike/weasyprint-report/`). **Representative visual and PDF/UA validation pending** before the full
migration is approved.
**Date:** 2026-08-18
**Related:** `api/report.py`, `tests/test_report_is_itself_accessible.py`,
`engine/pdf-analyser/analysers/rules/pdf/tagged_pdf.py`, ADR 0029 (vendor the PDF analyser),
`spike/weasyprint-report/` (the bounded spike + structural inspector).

## Context

The conformance report is a PDF ACP hands a customer as **audit evidence**. We hold it to the
standard it certifies other documents against, using our own vendored PDF engine
(`test_report_is_itself_accessible.py`). Two of the three findings our engine raised against it are
closed: `/Lang` (WCAG 3.1.1) and document-title + `DisplayDocTitle` (2.4.2).

The third is **open and CRITICAL**: `pdf.tagged` (WCAG 1.3.1, Info and Relationships). The report is
**not a tagged PDF** — it has no structure tree and no marked content, so a screen reader gets no
headings, no reading order, and no table structure, and the two charts (status donut, severity bars)
are undescribed vector drawings. `test_untagged_is_still_the_open_finding` pins this deliberately, so
the gap is recorded rather than implied by silence. Shipping an *inaccessible* accessibility report to
a hospital whose own auditor will run a checker on it is the credibility risk this ADR closes.

### Why it cannot be patched on the current renderer (verified)

The report is rendered with **ReportLab 4.5.1** (open source), via `reportlab.platypus`. Verified
locally against a fresh `reportlab==4.5.1` install:

- `reportlab.pdfgen.canvas.Canvas`, `platypus.SimpleDocTemplate`, and `pdfbase.pdfdoc` expose **no**
  marked-content or structure-tree API — no `beginMarkedContent`, no `StructElem`, no
  `StructTreeRoot` builder. The only hits for `StructTreeRoot` / `MarkInfo` in the source are the
  list of *allowed catalog keys* (`pdfdoc.py:1030`), not machinery that emits them.
- ReportLab therefore emits **no BDC/EMC operators and no MCIDs** in the content stream. Tagged-PDF /
  PDF/UA generation is a feature of the **commercial** ReportLab (`rlextra` / rml2pdf), not the
  open-source library.

**A fake structure tree is explicitly rejected.** We could post-process the ReportLab output with
`pikepdf` to set `/MarkInfo <</Marked true>>` and an empty `/StructTreeRoot` on the catalog. That
would turn our own detector green — and give a screen-reader user *nothing*, because there are no
MCIDs for structure elements to reference. Auto-tagging an untagged PDF is an **ASSISTED** (human-
confirmed) operation in ACP's own product; the report must not claim what we do not sell. Tripping the
rule without real tags is the exact dishonesty the self-test exists to prevent.

## Decision

**Migrate the conformance-report renderer from ReportLab to [WeasyPrint](https://weasyprint.org/)
(HTML/CSS → PDF), emitting the PDF/UA-1 tagged variant.** The report becomes an HTML template rendered
to a tagged PDF; the structure tree is derived from the HTML semantics, so tags are *real*, not
asserted.

### Proof of concept (verified locally, 2026-08-18)

`weasyprint==69.0`, semantic HTML (an `<h1>/<h2>` outline, a `<table>` with `<thead>/<th>`, an
`<img alt="…">`), rendered with:

```python
weasyprint.HTML(string=html).write_pdf("out.pdf", pdf_variant="pdf/ua-1")
```

Opened with `pikepdf` and checked against exactly what `TaggedPdfRule` checks:

| Catalog property | Result |
|---|---|
| `/MarkInfo` `/Marked` | **true** |
| `/StructTreeRoot` present | **true** |
| `/StructTreeRoot /K` (real children) | **true** — not an empty tree |
| `/Lang` | `en` |
| **`TaggedPdfRule` verdict** | **passes (0 findings)** |

Because the tree comes from HTML, three checks that pass *vacuously* today (an untagged PDF gives them
nothing to inspect) become **real**: `pdf.tagged` (1.3.1), `pdf.missing-alt-text` (1.1.1 — via
`<img alt>`), and `pdf.table-headers` (1.3.1 — via `<th>`).

**What this proves, precisely — and what it does not.** Passing `TaggedPdfRule` proves the *structural
objects exist* (`MarkInfo`, a populated `StructTreeRoot`). It does **not** prove the finished report is
PDF/UA-conformant or usable with a screen reader — WeasyPrint's own docs state that selecting
`pdf/ua-1` does not guarantee a valid document; the author must validate the result. Structural
correctness is necessary, not sufficient. The validation gate below is the honest bar.

## Validation gate (before the full migration is approved)

A bounded spike (`spike/weasyprint-report/`) rendered the four page types the report is built from —
cover, narrative, complex table, chart-heavy — and a structural inspector walked the result. **Hard
structural checks passed**: clean `H1→H2→H3` outline, tables tag as `Table/THead/TR/TH…TBody/TR/TD`
with DOM reading order, and running header/footer are Artifacts (kept out of reading order via `@page`
margin boxes). It also **surfaced two findings** that tag-existence hides:

1. **`<th scope>` emits no PDF `/Scope`** (0/16 TH scoped). Header association may still validate via
   table position — a **veraPDF** question, not an assumption.
2. **`aria-hidden` does not artifact an SVG** — the decorative chart became an *orphan* `/Figure`
   marked-content (real content, neither tagged-with-alt nor Artifact — PDF/UA forbids it). The
   "charts are decorative, exclude them" plan does not work as-is; a chart needs a real `alt` (or a
   genuine Artifact wrap) **plus** its adjacent data table — an HTML chart is not accessible by default.

The representative report must pass **all** of the following before the rewrite is committed — none is
satisfied by tag-existence alone:

- **Visual parity** for every page type (regression vs the current ReportLab output).
- Correct **heading hierarchy and reading order** *(checked structurally in the spike)*.
- **Properly scoped table headers** — finding 1; confirm in veraPDF.
- **Meaningful alt / artifact treatment for every chart** — finding 2; needs rework.
- Page furniture and decoration **excluded from reading order** *(header/footer confirmed)*.
- Searchable/selectable text and **working links**.
- **veraPDF or PAC 2024** validation (the automated PDF/UA gate — not `TaggedPdfRule` alone).
- A **manual NVDA / VoiceOver** spot check.
- Stable rendering and acceptable **runtime in CI and production** (WeasyPrint adds native deps).

### Why WeasyPrint over the alternatives

- Real semantic tags for free: headings, lists, tables (`<th>` → header cells), reading order (DOM
  order), and image alternatives (`alt`) map to PDF structure elements automatically.
- `pdf_variant="pdf/ua-1"` targets the accessibility profile directly.
- HTML/CSS is a more maintainable template than imperative `platypus` flowables, and the same markup
  is trivially reusable if we ever want an HTML report.

## Alternatives considered

- **Fake the catalog entries with pikepdf.** Rejected — an empty structure tree is dishonest and
  defeats the self-test's purpose (see above). This is the one option we must not take.
- **License commercial ReportLab (`rlextra`).** Keeps the existing template but adds cost and still
  requires authoring the tag structure by hand. Rejected for now — WeasyPrint gives real tags from
  markup we already know how to write, with no license.
- **Post-process with Adobe Acrobat's auto-tag / Accessibility Checker.** Not automatable in a
  headless pipeline, and auto-tag still needs human confirmation — the ASSISTED operation we won't
  claim as automatic.
- **Stay untagged, keep disclosing the gap.** The honest status quo, and acceptable *only* as an
  interim: the report already states its own limits and our engine flags it. But a CRITICAL
  self-finding on a customer deliverable is worth closing before the pilot.

## Consequences

- **CI adds native system dependencies.** WeasyPrint needs Pango, cairo, GDK-PixBuf and HarfBuzz. On
  the ubuntu backend job this is an `apt-get install` step (libpango-1.0-0, libpangocairo-1.0-0,
  libgdk-pixbuf-2.0-0, libharfbuzz…); it is heavier than the current pure-Python ReportLab path and
  wants caching. (Verified present on the dev machine — WeasyPrint imported and rendered without extra
  setup.)
- **`api/report.py` is rewritten** as an HTML template + a thin WeasyPrint render shim. The section
  content (decision block, scope-of-assertion incl. the estate funnel, per-document inventory table,
  remediation evidence appendix) ports to HTML/CSS.
- **The two charts must be reauthored accessibly, and this is the real work.** The spike proved an
  HTML chart is *not* accessible by default: an `aria-hidden` decorative SVG became an orphan `/Figure`
  (PDF/UA-forbidden), so each chart needs (a) a concise text alternative stating its *conclusion*,
  (b) an adjacent real data `<table>` so the numbers are in the tag tree, and (c) the decorative
  drawing genuinely excluded — as a proper Artifact or replaced by an image with a real `alt`. Not the
  `aria-hidden` shortcut this spike disproved.
- **Fonts must be embedded** for PDF/UA; pick an embeddable family and declare it in CSS.
- **The self-test flips.** Delete `test_untagged_is_still_the_open_finding` and add the alt-text and
  table-header self-checks the current test's docstring already asks for — the report is then held to
  1.1.1 and 1.3.1 with real evidence, and the 3.1.1 / 2.4.2 checks must keep passing on the new path.
- **Visual QA is required.** A customer-facing audit PDF must be re-reviewed page-by-page after the
  renderer swap (layout, pagination, charts, tables). This is why it is a scheduled change, not a
  blind one.

## Effort estimate (LOE)

~**2–4 developer-days**: template port (~1), accessible chart reauthoring (~0.5–1), CI system-deps +
font embedding (~0.5), self-test flip + new alt/table checks (~0.5), and full-report visual QA (~0.5–1).
Low technical risk (the tagging path is proven); the cost is porting fidelity and QA.

## Open questions (for the implementation PR)

- Keep both renderers behind a flag during transition, or cut over in one PR after visual sign-off?
- Charts as inline accessible SVG, or as data tables with a visual chart layered decoratively
  (`aria-hidden`)? The latter is the most robust for the tag tree.
- Which embeddable font family, and does it cover the report's glyph set (currency, arrows, the ✓/●
  marks)?

## Status / next step

Renderer selected; the bounded spike passed the hard structural checks and surfaced the two findings
above. **Next, on the representative sample (not the full report):** rework the chart treatment
(finding 2), then run veraPDF/PAC and an NVDA/VoiceOver pass (finding 1 + usability). Only if that
clears do we commit the full `report.py` migration. A hospital's own accessibility auditor is the
reader most likely to run a checker on this PDF, so it stays a **committed-for-pilot** item — but as a
*gated* one, not an unqualified "ready to build." Until it lands, the gap stays honestly disclosed and
the self-test keeps it visible.
