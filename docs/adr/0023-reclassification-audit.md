# ADR 0023 — Reclassification audit (assessment axis)

Companion to [ADR 0023](0023-two-axis-assessment-remediation-model.md). Task #174. Date: 2026-07-15.

## Purpose

The two-axis model gives every `(format × criterion)` an **assessment** lane (🟢 auto / 🟡 review / 🔴 human) and a **remediation** lane (⚡ auto / 🤖 assisted / 👤 human). The remediation axis is authored and already round-trip-proven by `tests/test_remediation_capability.py` (every ⚡ entry is tripped on a fixture, remediated, re-scanned, and asserted to clear; every 🤖 entry is asserted to make its proposer emit). The **assessment axis is derived** from remediation:

> `remediation == auto ⟹ 🟢`, else `🟡`, minus an explicit override list.

This audit answers: **is that derived assessment lane honest for every cell?** — i.e. does the code actually let ACP *certify a PASS* (🟢), only *detect a likely fail* (🟡), or *not assess at all* (🔴)?

## Method

The `⚡ auto` cells are 🟢 by construction and need no audit: a deterministic fixer that flips fail→pass on re-scan **is** proof the criterion is deterministically assessable. So the audit scope is exactly the **non-auto cells** — every `🤖 assisted` and `👤 human` remediation entry — checked against its detector with one question:

> **Is the criterion's conformance FULLY determined by a structural fact ACP checks (→ 🟢), or could a document that passes the check still fail on adequacy / meaning / threshold / duration (→ 🟡)?**

The detectors read: `api/scanner.py` (html), `api/office_structure.py` (office/pdf structure), `api/ocr.py` (images-of-text), `api/textchecks.py` (sensory, language-of-parts, reading level), `api/pii.py`.

## Findings

**The derived default holds for all but one cell.** "Not auto-fixable" turns out to correlate very strongly with "not deterministically certifiable" — which is expected: a criterion whose conformance were a pure structural fact would *have* a deterministic fixer, so it would already be ⚡. The non-auto criteria are non-auto precisely because they carry a semantic, heuristic, or threshold judgement:

| Category | Criteria (non-auto) | Why 🟡, not 🟢 (confirmed) |
|---|---|---|
| Alt / vision adequacy | 1.1.1 | missing-alt is deterministic, but alt *quality* is a judgement |
| Semantic text | 1.3.3 sensory · 3.1.2 language-of-parts · 3.1.5 reading level | phrase-match / langdetect / Flesch-Kincaid are heuristics or policy thresholds |
| OCR | 1.4.5 · 1.4.9 images-of-text | OCR can miss or false-positive; a clean scan ≠ certified pass |
| Link purpose | 2.4.4 · 2.4.9 | "click here" heuristic + duplicate-href; clear wording isn't verified |
| Reading order | 1.3.2 (docx/pdf/html) · 2.4.3 | floating-object / CSS-reorder / z-order are *risk* signals, not proof |
| Structure adequacy | 2.4.6 (xlsx/pptx/pdf) · 2.4.10 · 1.3.1 (pdf tags) | default-label / empty-title / tag presence is checkable, but *descriptiveness* is not |
| Threshold / duration | 1.4.2 audio (>3s unknown) · 2.5.8 target size (has WCAG exceptions) | the failing condition can't be fully proven from the file |
| Meaning-gated contrast | 1.4.11 non-text | contrast math is exact, but whether the element is *meaningful* is a judgement |
| Media alternatives | 1.2.1 / 1.2.2 / 1.2.3 | a missing `<track>` is detectable, but burned-in captions could still pass |

### Correction (1 cell): docx 1.4.8 Visual Presentation → 🟢

`DOCX_JUSTIFIED_TEXT` fires on an explicit `<w:jc w:val="both"|"distribute">` attribute (`office_structure._JC_BOTH`). Justified body text present = a real 1.4.8 failure; **absent = a certifiable pass** — the conformance is fully determined by a structural attribute. Yet the remediation is *not* auto: forcing left-alignment is an opt-in a human elects (some authors want justification), so it ships as a 🤖 one-click card, not a silent ⚡ fix.

→ **docx 1.4.8 is 🟢 assess / 🤖 remediate.** Added to `ASSESSMENT_OVERRIDES`.

### Consequence: the two axes are independent (a wrong invariant, removed)

The original P0.3 contract test asserted `assessment == 🟢 ⟹ remediation == ⚡` ("a certifiable pass requires a deterministic fixer"). **1.4.8 disproves it.** That reverse implication was a derivation artifact, not a truth — the whole point of the two-axis model is that *how ACP assesses* and *how ACP fixes* are orthogonal. The assertion is removed; the 🟢/🤖 exception is pinned explicitly instead.

The forward direction (`⚡ ⟹ 🟢`) remains sound and is what the derivation still relies on.

### 🔴 human-only — unchanged, still exactly one

`pptx 2.1.1` Keyboard: keyboard operability is a property of the runtime that presents the deck, not of the file, so ACP can collect no file-level evidence. Every other criterion has at least a heuristic detector (🟡) or a deterministic one (🟢). The control-free `2.4.3 / 2.1.1` cells on docx/xlsx/pdf are simply *absent* from the capability table → they render ⚪ N/A, which is correct (no detector, not a fabricated verdict).

## Borderlines deliberately kept 🟡 (ADR 0016 — humility over over-claim)

These have a deterministic *detector* but a conformance that isn't fully determined by it; the honest lane is 🟡, and the customer can elect to treat them as pass-on-clean if they wish:

- **2.4.10 docx** (section headings) — heading styles present is checkable, but "organizes the content" is not.
- **2.4.6 pptx** (empty title) — an empty title is a fail; a *present but vague* title still passes the check.
- **2.5.8 html** (target size) — pixel size is exact, but WCAG 2.5.8 has inline/essential exceptions.
- **1.4.2 pptx** (auto-audio) — auto-start is detectable; the ">3 seconds" that makes it fail is not.

## Outcome & open decision

- **Result:** 89 of 90 assessment lanes confirmed honest; **1 correction** (docx 1.4.8 → 🟢); **1 over-strong invariant removed**. The matrix in ADR 0023 is unchanged (1.4.8 is outside the 20 document-core).
- **Open honesty decision (flagged, not yet actioned — its own task):** in the per-file FileDrawer coverage table, a 🟡 review-lane criterion that ALSO has a pass/fail detector (e.g. 1.1.1: real missing-alt check) currently shows **PASS** when the scan finds nothing. Per this model that over-claims — ACP can't certify a 1.1.1 pass (alt adequacy). The audited position: **a review-lane criterion with no finding should read "no issue found — verify", never a green certified PASS.** Implementing it flips many drawer rows and needs its own careful change; recommended as the next follow-up.
