# Assessment Capability Matrix — WCAG 2.1 AA by document format

*Snapshot as of live version **v2026.7.15.5** (2026-07-15).*

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
|----|-----------|:---:|:----:|:----:|:----:|:---:|:----:|
| 1.1.1 | Non-text Content | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 1.3.1 | Info and Relationships | A | 🟢 | 🟢 | 🟢 | 🟡 | 🟢 |
| 1.3.2 | Meaningful Sequence | A | 🟡 | 🟢 | 🟢 | 🟡 | 🟡 |
| 1.3.3 | Sensory Characteristics | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 2.4.6 | Headings and Labels | AA | 🟢 | 🟡 | 🟡 | 🟡 | 🟢 |
| 3.1.1 | Language of Page | A | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| 3.1.2 | Language of Parts | AA | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 1.4.4 | Resize Text | AA | ⚪ | ⚪ | 🟡 | ⚪ | 🟢 |
| 1.4.5 | Images of Text | AA | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 1.4.10 | Reflow | AA | 🟡 | ⚪ | 🟡 | ⚪ | 🟢 |
| 1.4.12 | Text Spacing | AA | 🟡 | ⚪ | 🟡 | 🟡 | 🟢 |
| 1.4.1 | Use of Color | A | 🟡 | 🟡 | ⚪ | 🟡 | 🟢 |
| 1.4.3 | Contrast (Minimum) | AA | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| 1.4.11 | Non-text Contrast | AA | 🟡 | ⚪ | 🟡 | 🟡 | 🟡 |
| 2.4.2 | Page Titled | A | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| 2.4.3 | Focus Order | A | ⚪ | ⚪ | 🟡 | ⚪ | 🟢 |
| 2.4.4 | Link Purpose (In Context) | A | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 2.1.1 | Keyboard | A | ⚪ | ⚪ | 🔴 | ⚪ | 🔵 |
| 2.1.2 | No Keyboard Trap | A | 🟡 | 🟡 | 🟡 | ⚪ | 🔵 |
| 4.1.2 | Name, Role, Value | A | 🟡 | 🟡 | 🟡 | ⚪ | 🟢 |

## Assessable totals

"Assessable" = ACP produces *something* on the assessment axis — a verdict (🟢) or an
evidence-backed flag (🟡). 🔴/⚪/🔵 are not ACP assessments.

| Format | Assessable | 🟢 auto | 🟡 review | 🔴 human | ⚪ N/A | 🔵 AT |
|--------|:----------:|:------:|:--------:|:-------:|:-----:|:-----:|
| DOCX | **17 / 20** | 5 | 12 | 0 | 3 | — |
| XLSX | **14 / 20** | 5 | 9 | 0 | 6 | — |
| PPTX | **18 / 20** | 5 | 13 | 1 | 1 | — |
| PDF | **14 / 20** | 3 | 11 | 0 | 6 | — |
| HTML | **18 / 20** | 11 | 7 | 0 | 0 | 2 |

## Why the ⚪ / 🔴 / 🔵 cells are honest, not gaps

- **⚪ N/A** — the barrier can't exist in that container. A fixed-canvas slide/page has no
  reflow (1.4.10), no resize-text rewrap (1.4.4), and no focus order (2.4.3) the way a live web
  page does; a PDF has no interactive keyboard trap surface (2.1.2/4.1.2). Marking these ⚪ is
  correct — inventing a detector there would fabricate a signal.
- **🔴 human-only** — PPTX 2.1.1 Keyboard is genuinely author-intent/runtime; no static or
  structural read can certify it.
- **🔵 AT** — HTML keyboard criteria (2.1.1/2.1.2) are only provable by interaction /
  assistive-tech testing, so they sit outside the static engine by definition.

Notably **PDF 1.4.10 Reflow is deliberately left ⚪, not built as a proxy**: unlike fixed-canvas
Office, PDF reflow is a universal concern, so a "narrowest column" structural heuristic would
produce noise rather than honest evidence (ADR 0025).

## Regenerating

This table is produced from the live frontend logic. From `frontend/`:

```js
// gen_assess_table.mjs
import { assessmentIn, DOCUMENTS_20 } from './src/assessCoverage.js'
import { WCAG } from './src/wcagCatalog.js'
const NAME = Object.fromEntries(WCAG.map(c => [c.sc, c.name]))
const LVL  = Object.fromEntries(WCAG.map(c => [c.sc, c.level]))
const FMTS = ['docx','xlsx','pptx','pdf','html']
const SYM = { auto:'🟢', review:'🟡', human:'🔴', na:'⚪', gap:'🟠', at:'🔵' }
console.log(`| SC | Criterion | Lvl | ${FMTS.map(f=>f.toUpperCase()).join(' | ')} |`)
console.log(`|----|-----------|-----|${FMTS.map(()=>':--:').join('|')}|`)
for (const sc of DOCUMENTS_20) {
  const cells = FMTS.map(f => SYM[assessmentIn(sc, f)])
  console.log(`| ${sc} | ${NAME[sc]} | ${LVL[sc]} | ${cells.join(' | ')} |`)
}
```

```
node gen_assess_table.mjs
```

The per-format tallies are also asserted in `frontend/src/assessCoverage.test.js` (the `EST`
fixture), so a detector change that shifts a cell will fail that test until this snapshot and the
fixture are both updated.
