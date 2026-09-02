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
2. **An HTML chart is not accessible by default** — *resolved in the spike (iteration 2).*
   `aria-hidden` on an inline `<svg>` did not artifact it; it left an *orphan* `/Figure` marked-content
   (real content, neither tagged-with-alt nor Artifact — PDF/UA forbids it), and `<svg role="img"
   aria-label>` was ignored for tagging too. The treatment that works, verified by probe: an
   `<img alt="…conclusion…">` carrying the chart as a data-URI SVG tags as a `/Figure` **with** `/Alt`
   and leaves no orphan, beside a data table with the exact counts. So "charts are decorative, exclude
   them" is wrong; "chart is a Figure with a conclusion-stating alt + a data table" is the pattern.

The representative report must pass **all** of the following before the rewrite is committed — none is
satisfied by tag-existence alone:

- **Visual parity** for every page type (regression vs the current ReportLab output).
- Correct **heading hierarchy and reading order** *(checked structurally in the spike)*.
- **Properly scoped table headers** — finding 1; confirm in veraPDF.
- **Meaningful alt / artifact treatment for every chart** — finding 2, *resolved* (chart is a Figure
  with a conclusion-stating `/Alt` + a data table); still worth a screen-reader read.
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

## Addendum — 2026-09-01: the gate has now actually been run

Everything above is left as written; this records what was measured afterwards, and corrects two
things the ADR asserts that are no longer true.

**"veraPDF or PAC 2024" was never run.** `spike/weasyprint-report/README.md:66` records it as "not
runnable here (no local Java)", and that was the state of the whole decision: the automated gate the
migration is conditioned on had not produced a number. **Java 21 is present**, veraPDF 1.30.2 runs,
and it has now been pointed at both renderers. So the paragraphs above that say "confirm in veraPDF"
describe work that has happened.

**The baseline is not ReportLab.** The ADR compares against `report.py`'s ReportLab output, but what
serves `/scans/{sid}/report.pdf` today is `api/report_tagged.py` — a Chromium
`--generate-tagged-pdf` pipeline. "Visual parity" therefore means parity with that, and the
comparison in this slice was made against it.

### What veraPDF says about the renderer we ship today

    clause 7.1 test 8   x1   no XMP metadata stream in the catalog. Chromium writes none; PDF/UA
                             requires one, and it is what carries the UA identifier.
    clause 7.1 test 3   x7   content neither marked as Artifact nor tagged as real content.
                             These are Chromium's own print header and footer.

    NOT PDF/UA-1 conformant.

The passed-check total is around 10,000 and is deliberately not quoted precisely: it moves between
builds of the same renderer (10083 and 10088 on two runs an hour apart, because the timestamp and
object ids change what there is to check). The eight failures and their breakdown are the stable
fact, and are what the fixture pins.

Pinned as an executable fact in `tests/test_report_pdfua_gap.py`, with the validator proven
non-vacuous in both directions — a known-untagged corpus PDF must fail and a known-good tagged
document must pass, or "veraPDF says FAIL" is a finding about the validator.

**A second defect fell out of the first.** Those seven orphans are the print furniture, and the
footer Chromium draws is the local path the HTML was rendered from:

    file:///tmp/acp_report_<random>/report.html

printed on every page of a document ACP hands a customer as audit evidence. The renderer passes
`--print-to-pdf-no-header` and in this Chromium build it does not suppress it.

### What veraPDF says about the candidate

`api/report_weasy.py` — the same content model, rendered through WeasyPrint's `pdf/ua-1` variant —
**passes, 0 failed checks**, with a real structure tree: no `/StructTreeRoot` is fabricated anywhere
in this path.

### Two things veraPDF passing does not mean, learned the expensive way

Recorded because both defects survived a green validator and a green structural suite, and only a
person looking at the page found them:

1. **The font stack was interpolated through an autoescaping Jinja environment**, arriving as
   `font-family: &#34;Liberation Sans&#34;, …` — invalid CSS, silently dropped, the entire report
   set in WeasyPrint's default serif. veraPDF: 0 failures. Structural tests: 13/13 green.
2. **Retagging row cells as `<th scope="row">` also restyled them** — bold, shaded, heavier rule —
   redesigning two tables in the name of a structure fix. ISO 14289 wants the cell tagged as a
   header and says nothing about its weight.

The lesson for the checklist above: `veraPDF or PAC 2024` and the structural suite are gates on
*semantics*. Neither is a gate on the document still looking like the document, and neither can be.

### Where the migration actually stands

| Gate | State |
| --- | --- |
| Structural (heading outline, TH + scope, Figure `/Alt`, Link, lang, title) | 15 tests, green |
| veraPDF ua1 on the candidate | PASS, 0 failures |
| veraPDF ua1 on the shipped renderer | FAIL, 8 — pinned as a regression fixture |
| Visual parity vs Chromium | reviewed page by page; 2 pages both, uniform ~7px offset from mid-page down, non-accumulating |
| **PAC 2024** | **not run — Windows only** |
| **NVDA / VoiceOver** | **not run — no screen reader here** |

`scripts/build_report_review_packet.py` builds what a reviewer needs for the last two: both PDFs,
both rendered page by page with amplified differences, the veraPDF report, and a REVIEW.md naming
what is still unverified.

**Nothing is switched over.** `api/report_tagged.py`, `api/report.py` and `api/routes/scans.py` are
untouched, and the cutover stays gated on PAC 2024 and a screen-reader pass — which is what this ADR
asked for, and is now the only part of it outstanding.

## Addendum 2 — 2026-09-02: the cutover happened, with two gates still open

The paragraph immediately above is superseded and deliberately left standing, because what changed
is a decision and not a fact: the owner asked for the renderer to be wired in. It now serves
`/scans/{sid}/report.pdf`.

**PAC 2024 and the NVDA/VoiceOver pass have still not been run.** This ADR asks for both before
replacing the renderer, and they were not done — that is a knowing exception, recorded here rather
than quietly dropped from a checklist. What was run: veraPDF ua1 (0 failures on the endpoint's own
output, against the Chromium renderer's 14 on the same document), the structural suite, and a
page-by-page visual comparison.

**`ACP_REPORT_RENDERER=tagged` restores the previous renderer at runtime, with no redeploy.** That
switch exists because of the two open gates; a rollback needing a build is not one anybody reaches
for at the moment they need it. Both directions were measured rather than assumed — the default
gives 0 ua1 failures and no path leak, `tagged` gives 14 and the leak returns.

### What wiring it in actually required, none of which was the route

The route change is one import and one call. The rest is what would have made it fail in
production instead of in review:

- **`weasyprint` was in no requirements file.** It merged as dead code and nothing installed it, so
  wiring the route alone would have fallen through to Chromium on every request — silently, since
  the fallback is what keeps the endpoint up.
- **pip cannot install what WeasyPrint dlopens**: pango, pangoft2, harfbuzz, fontconfig (gobject
  arrives with pango). That list is read off `weasyprint.text.ffi`'s own dlopen calls —
  `spike/weasyprint-report/requirements.txt` says "Pango, cairo, GDK-PixBuf, HarfBuzz", the
  pre-53 cairo-era list, which names two libraries WeasyPrint 69 never loads.
- **`fonts-dejavu-core` is load-bearing.** The File Inventory prints U+2713 and U+2717 and
  Liberation Sans carries neither; without DejaVu they are `.notdef` boxes in the certification
  column.

**All three of those were already fixed on `main` before this cutover landed, by #1197/#1198/#1199
and not by this change** — `weasyprint==69.0` is declared, the serving image installs the native
stack and DejaVu, and CI installs veraPDF so the conformance half of the suite evaluates instead
of skipping. This change found them independently while preparing to wire the route and then
dropped its own versions rather than shipping a second declaration beside a first. What it keeps
is `tests/test_report_renderer_wiring.py`, which pins them statically so that the cutover cannot
outlive them: they are now load-bearing for a live endpoint rather than for a module nothing
called, and the way they would break is silent — a fallback serving a non-conformant report with
a 200.

### Known gaps, not addressed here

Noted while measuring, left alone because they belong to the PDF/UA gate work rather than to the
cutover, and duplicating that work is what this change has already had to unwind once:

- `deploy/test/Dockerfile` installs none of the native stack, while installing
  `api/requirements.txt`, which now carries weasyprint. A missing library raises `OSError`, which
  `pytest.importorskip` does not catch, so the report suites would ERROR at collection in that
  image rather than skip.
- `azure-pipelines.yml` installs neither the native stack nor veraPDF, so the same suite means
  something different there than in `ci.yml` — which that file's own dependency-step comment says
  it must not.
