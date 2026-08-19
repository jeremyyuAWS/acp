# WeasyPrint tagged-PDF spike — conformance report (ADR 0034)

A **bounded** spike, not the renderer migration. It exists to answer the questions that passing our
own `TaggedPdfRule` does **not** answer, on a representative artifact, before committing the 2–4 day
rewrite of `api/report.py`.

## What it is

`sample_report.py` renders the four page types the full report is built from — a **cover/decision**
page, a **narrative** page, one **complex table**, and one **chart-heavy** page — to a `pdf/ua-1`
tagged PDF via WeasyPrint. `inspect_tags.py` walks the resulting structure tree and reports the
*semantics*, separating hard structural must-haves from PDF/UA-nuance findings.

```
python -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python inspect_tags.py      # builds sample_report.pdf, then inspects it
```

## What the spike DID prove (structural)

Run against WeasyPrint 69 / reportlab-free, verified locally:

- `/MarkInfo /Marked true`, a `/StructTreeRoot` with real children, `/Lang=en-US`, `DisplayDocTitle`
  true — passes ACP's own `TaggedPdfRule`, `DocumentLanguageRule`, `DisplayTitleRule`.
- **Heading hierarchy is a clean outline** — `H1 → H2 → H3` with no skipped levels.
- **Tables tag as** `Table > THead > TR > TH … TBody > TR > TH/TD`, and reading order follows the DOM.
- **Running header/footer are Artifacts** (41 Artifact marked-content sequences) — page furniture is
  kept out of the reading order automatically via `@page` margin boxes.

## What the spike SURFACED (findings for the gate — the point of doing it)

Two real issues that "tags exist" would have hidden:

1. **`<th scope>` does not become a PDF `/Scope` attribute.** WeasyPrint tags header cells as `/TH`
   but emits no explicit `/Scope`; 0 of 16 TH cells carried one. PDF/UA can associate headers by
   table position, so this may still validate — **but it must be confirmed in veraPDF**, not assumed.
2. **`aria-hidden` does not artifact an SVG.** The decorative bar chart produced an **orphan
   `/Figure` marked-content** (in the content stream, not linked into the struct tree) — real content
   that is neither tagged-with-alt nor an Artifact, which PDF/UA forbids. **The "charts are
   decorative, exclude them" approach does not work as-is in WeasyPrint** and needs a different
   technique (e.g. render the chart as an image with a proper `alt`, or wrap it so it is a true
   Artifact, keeping the adjacent data table as the real information).

Both are exactly the "document semantics, not tag existence" risks that make this a spike.

## What the spike does NOT prove — the validation gate (from review)

Structural correctness is necessary, **not sufficient**, for PDF/UA. WeasyPrint's own docs say
selecting `pdf/ua-1` does not guarantee a valid document. Before the full migration is approved, a
representative report must pass **all** of:

- [ ] **Visual parity** for every page type (regression against the current ReportLab output)
- [x] Correct heading hierarchy and reading order — *checked structurally here*
- [ ] **Properly scoped table headers** — finding #1 above; **confirm in veraPDF**
- [ ] Meaningful **alt text or artifact treatment for every chart** — finding #2 above; **needs rework**
- [x] Page header/footer/decorative elements excluded from reading order — *header/footer confirmed*
- [ ] Searchable/selectable text and working links (a `<a href>` link tags as `Link`; selection
      needs a manual check — WeasyPrint text is real glyphs, not outlines)
- [ ] **veraPDF or PAC 2024 validation** — not runnable here (no local Java); the required automated gate
- [ ] **Manual screen-reader spot check** — NVDA (Windows) or VoiceOver (macOS)
- [ ] Stable rendering and acceptable runtime in CI and production (WeasyPrint adds native deps:
      Pango, cairo, GDK-PixBuf, HarfBuzz)

## Recommendation

**Proceed to the full migration only after** the chart-treatment rework (finding #2) and a veraPDF +
screen-reader pass on this representative sample. The direction is sound — WeasyPrint produces a real,
structurally-correct tag tree — and the remaining risk is document semantics and visual parity, not
whether the renderer can tag. Roadmap status: *renderer selected · POC passed structural detector ·
representative visual and PDF/UA validation pending.*
