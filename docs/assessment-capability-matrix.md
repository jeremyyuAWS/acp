# Assessment Capability Matrix — WCAG 2.1 AA by document format

*Generated from `frontend/src/assessCoverage.js` at commit **4289599** (2026-08-04). The stamp is
a commit rather than a deploy version because that is what the table is derived from — anyone can
check it out and reproduce these cells exactly; a deploy version cannot be re-run.*

This is a **derived** reference, not a source of truth. The authoritative data is
`frontend/src/assessCoverage.js` (`assessmentIn(sc, fmt)`), which mirrors the backend
`api/store.py` `REVIEW_FORMATS` and `api/remediation_capability.py` `CAPABILITY`. When those
change, regenerate this table (see [Regenerating](#regenerating)) rather than hand-editing it.

It answers one question: **"of the WCAG criteria that matter for documents, which can ACP
*assess* in each file type — and how honestly?"** It is deliberately decoupled from any single
scan, so a criterion ACP fully supports never looks like a hole just because an estate had no
instances of it.

The two-axis model (assessment ⟂ remediation) is defined in
[ADR 0023](adr/0023-two-axis-assessment-remediation-model.md); the render-gated proxies in
[ADR 0024](adr/0024-render-gated-assessment-criteria.md); the PDF measurements in
[ADR 0025](adr/0025-pdf-render-verified-measurements.md). This page shows only the **assessment**
axis. For the remediation axis (⚡/🤖/👤) see the Coverage scorecard in the app.

## Legend

| Symbol | Assessment lane | Meaning |
|:------:|-----------------|---------|
| 🟢 | **auto** | ACP certifies a **pass *and* a fail** — deterministic/computable. The honest headline. |
| 🟡 | **review** | ACP detects **evidence of a likely issue**; a human confirms. Never a certified pass. |
| 🔴 | **human-only** | ACP **can't assess** — author intent or runtime behaviour, no detector can honestly claim it. |
| ⚪ | **N/A** | The barrier **can't exist** in this file type. |
| 🔵 | **AT** | Applies, but only provable by **interaction / assistive-tech testing** — never static analysis. |

The core honesty rule (ADR 0016 / ADR 0023): auto-assess 🟢 **only** where ACP can certify a
PASS, not merely detect a FAIL. So alt-text adequacy (1.1.1), link purpose (2.4.4), and use of
colour (1.4.1) are 🟡 — not 🟢 — even though ACP has detectors for them.

## The 20-criterion document core

| SC | Criterion | Lvl | DOCX | XLSX | PPTX | PDF | HTML |
|----|-----------|:---:|:----:|:----:|:----:|:----:|:----:|
| 1.1.1 | Non-text Content | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 1.3.1 | Info and Relationships | A | 🟢 | 🟢 | 🟢 | 🟡 | 🟢 |
| 1.3.2 | Meaningful Sequence | A | 🟡 | 🟢 | 🟢 | 🟡 | 🟡 |
| 1.3.3 | Sensory Characteristics | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 2.4.6 | Headings and Labels | AA | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 3.1.1 | Language of Page | A | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| 3.1.2 | Language of Parts | AA | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 1.4.4 | Resize Text | AA | ⚪ | ⚪ | 🟡 | ⚪ | 🟢 |
| 1.4.5 | Images of Text | AA | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 1.4.10 | Reflow | AA | 🟡 | ⚪ | 🟡 | ⚪ | 🟢 |
| 1.4.12 | Text Spacing | AA | 🟡 | ⚪ | 🟡 | 🟡 | 🟢 |
| 1.4.1 | Use of Color | A | 🟡 | 🟡 | ⚪ | 🟡 | 🟢 |
| 1.4.3 | Contrast (Minimum) | AA | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| 1.4.11 | Non-text Contrast | AA | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 2.4.2 | Page Titled | A | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| 2.4.3 | Focus Order | A | ⚪ | ⚪ | 🟡 | 🟡 | 🟢 |
| 2.4.4 | Link Purpose (In Context) | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 2.1.1 | Keyboard | A | ⚪ | ⚪ | 🔴 | ⚪ | 🔵 |
| 2.1.2 | No Keyboard Trap | A | 🟡 | 🟡 | 🟡 | ⚪ | 🔵 |
| 4.1.2 | Name, Role, Value | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟢 |

## Assessable totals

"Assessable" = ACP produces *something* on the assessment axis — a verdict (🟢) or an
evidence-backed flag (🟡). 🔴/⚪/🔵 are not ACP assessments.

| Format | Assessable | 🟢 auto | 🟡 review | 🔴 human | ⚪ N/A | 🔵 AT |
|--------|:----------:|:------:|:--------:|:-------:|:-----:|:-----:|
| DOCX | **17 / 20** | 4 | 13 | 0 | 3 | — |
| XLSX | **15 / 20** | 5 | 10 | 0 | 5 | — |
| PPTX | **18 / 20** | 5 | 13 | 1 | 1 | — |
| PDF | **16 / 20** | 3 | 13 | 0 | 4 | — |
| HTML | **18 / 20** | 10 | 8 | 0 | 0 | 2 |

## Why the ⚪ / 🔴 / 🔵 cells are honest, not gaps

- **⚪ N/A** — the barrier can't exist in that container. A fixed-canvas slide/page has no
  reflow (1.4.10), no resize-text rewrap (1.4.4), and no focus order (2.4.3) the way a live web
  page does; a PDF has no interactive keyboard trap surface (2.1.2). Marking these ⚪ is
  correct — inventing a detector there would fabricate a signal.

  **PDF 4.1.2 used to sit in this list and no longer does.** It is 🟡, not ⚪: an AcroForm PDF
  does expose components with a name, role and value, so the barrier was always capable of
  existing there — the cell was ⚪ because nothing had declared the criterion, which is a
  different statement from "cannot apply". The detector reads `/TU`, `/FT` and `/V` from the
  field dictionary and is exact within that subset, but it is silent on components expressed
  through the tagged-structure tree, so 🟡 rather than 🟢.
- **🔴 human-only** — PPTX 2.1.1 Keyboard is genuinely author-intent/runtime; no static or
  structural read can certify it.
- **🔵 AT** — HTML keyboard criteria (2.1.1/2.1.2) are only provable by interaction /
  assistive-tech testing, so they sit outside the static engine by definition.

Notably **PDF 1.4.10 Reflow is deliberately left ⚪, not built as a proxy**: unlike fixed-canvas
Office, PDF reflow is a universal concern, so a "narrowest column" structural heuristic would
produce noise rather than honest evidence (ADR 0025).

## Regenerating

Both tables are produced from the live frontend logic. From `frontend/`:

```
node scripts/gen_assess_table.mjs
```

Paste its two tables over "The 20-criterion document core" and "Assessable totals", and update
the commit stamp at the top. The script emits the totals table as well as the grid — they are
derived from the same call, and leaving the second one to be updated by hand is how it drifted
before (see below).

### What guards this page

`frontend/src/matrixDoc.test.js` regenerates both tables and asserts this file matches. That is
the only thing keeping this page true; if you change a detector, that test fails and tells you
to re-run the generator.

**It was added on 2026-08-04 because the page had been wrong for three weeks and this section
said otherwise.** The previous text claimed the `EST` fixture in `assessCoverage.test.js` meant
"a detector change that shifts a cell will fail that test until this snapshot and the fixture
are both updated". Only the second half was ever true. `EST` pins `assessCoverage.js` against
itself and never reads this file, so when three cells moved —

| Cell | Was | Now | Landed in |
|---|:--:|:--:|---|
| 2.4.6 DOCX | 🟢 | 🟡 | `997b7d0` — level-stepping is not descriptiveness |
| 2.4.6 HTML | 🟢 | 🟡 | `0be9e00` (#26) — same reason |
| 4.1.2 PDF | ⚪ | 🟡 | `04b6213` (#70) — the criterion was undeclared, not inapplicable |

— the fixture was updated in the same commits, its comments explaining each move, while this
page kept printing the superseded numbers. Nothing failed, because nothing was looking. A
document that names a guard it does not have is worse than one that admits it has none: the
claim is what stops the next person checking.
