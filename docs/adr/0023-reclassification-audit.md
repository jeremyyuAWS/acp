# ADR 0023 — Reclassification audit (assessment axis)

Companion to [ADR 0023](0023-two-axis-assessment-remediation-model.md). Task #174. Date: 2026-07-15.

## Purpose

The two-axis model gives every `(format × criterion)` an **assessment** lane (🟢 auto / 🟡 review / 🔴 human) and a **remediation** lane (⚡ auto / 🤖 assisted / 👤 human). The remediation axis is authored and already round-trip-proven by `tests/test_remediation_capability.py` (every ⚡ entry is tripped on a fixture, remediated, re-scanned, and asserted to clear; every 🤖 entry is asserted to make its proposer emit). The **assessment axis is derived** from remediation:

> `remediation == auto ⟹ 🟢`, else `🟡`, minus an explicit override list.

This audit answers: **is that derived assessment lane honest for every cell?** — i.e. does the code actually let ACP *certify a PASS* (🟢), only *detect a likely fail* (🟡), or *not assess at all* (🔴)?

## Method

The `⚡ auto` cells are 🟢 by construction and need no audit: a deterministic fixer that flips fail→pass on re-scan **is** proof the criterion is deterministically assessable. So the audit scope is exactly the **non-auto cells** — every `🤖 assisted` and `👤 human` remediation entry — checked against its detector with one question:

> **Superseded — see [Correction 2](#correction-2-docx-246-headings-and-labels--) below.** Exempting the ⚡ cells from audit was the method's one flaw, and it is how docx 2.4.6 escaped. "Fixer clears the finding on re-scan" only proves deterministic assessability when the detector's coverage **is** the criterion; where a fixer clears the one narrow signal its own detector emits, the loop closes over a subset and proves nothing about the rest. The ⚡ cells needed the same question asked of them as the 🤖/👤 cells.

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

Note the shape of that "Structure adequacy" row: 2.4.6 is 🟡 on **xlsx, pptx and pdf** — every format whose remediation is non-auto, i.e. every format the audit actually looked at. docx 2.4.6 is missing from the row not because it differs, but because it was ⚡ and therefore out of scope. Same criterion, same reasoning, exempted by the method.
| Threshold / duration | 1.4.2 audio (>3s unknown) · 2.5.8 target size (has WCAG exceptions) | the failing condition can't be fully proven from the file |
| Meaning-gated contrast | 1.4.11 non-text | contrast math is exact, but whether the element is *meaningful* is a judgement |
| Media alternatives | 1.2.1 / 1.2.2 / 1.2.3 | a missing `<track>` is detectable, but burned-in captions could still pass |

### Correction (1 cell): docx 1.4.8 Visual Presentation → 🟢

`DOCX_JUSTIFIED_TEXT` fires on an explicit `<w:jc w:val="both"|"distribute">` attribute (`office_structure._JC_BOTH`). Justified body text present = a real 1.4.8 failure; **absent = a certifiable pass** — the conformance is fully determined by a structural attribute. Yet the remediation is *not* auto: forcing left-alignment is an opt-in a human elects (some authors want justification), so it ships as a 🤖 one-click card, not a silent ⚡ fix.

→ **docx 1.4.8 is 🟢 assess / 🤖 remediate.** Added to `ASSESSMENT_OVERRIDES`.

### Consequence: the two axes are independent (a wrong invariant, removed)

The original P0.3 contract test asserted `assessment == 🟢 ⟹ remediation == ⚡` ("a certifiable pass requires a deterministic fixer"). **1.4.8 disproves it.** That reverse implication was a derivation artifact, not a truth — the whole point of the two-axis model is that *how ACP assesses* and *how ACP fixes* are orthogonal. The assertion is removed; the 🟢/🤖 exception is pinned explicitly instead.

The forward direction (`⚡ ⟹ 🟢`) remains sound and is what the derivation still relies on. **— Also falsified; see Correction 2.** It is sound only under an unstated precondition (the detector covers the whole criterion) that docx 2.4.6 violates. The derivation still relies on it, now with an explicit override for the cell where it fails.

### Correction 2: docx 2.4.6 Headings and Labels → 🟡

*Added after the original audit. This cell was never examined, because the method above exempted ⚡ cells.*

2.4.6 asks whether headings and labels **describe topic or purpose**. The only docx detector, `office_structure.DOCX_HEADING_SKIP`, decides a strictly narrower fact: whether heading *levels* step by one. `remediate_office` then clamps any gap, the re-scan is clean, and the derivation read that clean re-scan as a certified pass for the full criterion.

The loop is closed and self-confirming: detector finds level gaps → fixer closes level gaps → re-scan finds no level gaps. Nothing in it ever bore on descriptiveness. Two fixtures run through the real pipeline (`checks_for` → `filter_issues_to_target` → `_rule_outcome`) showed what that certified:

- A flawless `H1 → H2 → H3` outline whose headings read "Section 1" / "Untitled" / "asdf" → **PASS**.
- An outline that starts at H3 with no H1 or H2 anywhere → **PASS**, because the skip check's `prev_level > 0` guard means the first heading is never judged.

Whether a heading describes its section is a judgement no OOXML property settles, so 🟡 is the honest ceiling — the same lane 2.4.6 already carries on xlsx, pptx and pdf.

→ **docx 2.4.6 is 🟡 assess / ⚡ remediate.** Added to `ASSESSMENT_OVERRIDES`. The remediation lane is untouched and stays ⚡: the heading-skip closure is genuinely deterministic and round-trip proven. Only the claim that it certifies a pass was wrong.

This is the mirror of the 1.4.8 correction, and completes the proof that the axes are independent in **both** directions: 1.4.8 is 🟢 assess / 🤖 remediate (assessable, not auto-fixable); 2.4.6 docx is 🟡 assess / ⚡ remediate (auto-fixable, not certifiable).

### 🔴 human-only — unchanged, still exactly one

`pptx 2.1.1` Keyboard: keyboard operability is a property of the runtime that presents the deck, not of the file, so ACP can collect no file-level evidence. Every other criterion has at least a heuristic detector (🟡) or a deterministic one (🟢). The control-free `2.4.3 / 2.1.1` cells on docx/xlsx/pdf are simply *absent* from the capability table → they render ⚪ N/A, which is correct (no detector, not a fabricated verdict).

## Borderlines deliberately kept 🟡 (ADR 0016 — humility over over-claim)

These have a deterministic *detector* but a conformance that isn't fully determined by it; the honest lane is 🟡, and the customer can elect to treat them as pass-on-clean if they wish:

- **2.4.10 docx** (section headings) — heading styles present is checkable, but "organizes the content" is not.
- **2.4.6 pptx** (empty title) — an empty title is a fail; a *present but vague* title still passes the check.
- **2.5.8 html** (target size) — pixel size is exact, but WCAG 2.5.8 has inline/essential exceptions.
- **1.4.2 pptx** (auto-audio) — auto-start is detectable; the ">3 seconds" that makes it fail is not.

## Outcome & open decision

- **Result (as originally recorded):** 89 of 90 assessment lanes confirmed honest; **1 correction** (docx 1.4.8 → 🟢); **1 over-strong invariant removed**. The matrix in ADR 0023 is unchanged (1.4.8 is outside the 20 document-core).
- **Revised:** **2 corrections** — docx 1.4.8 → 🟢, and docx 2.4.6 → 🟡 (Correction 2). Unlike 1.4.8, 2.4.6 **is** in the 20 document-core, so this one *does* change ADR 0023's matrix: its docx cell goes 🟢/⚡ → 🟡/⚡ (marked ‡ there). The "89 of 90 confirmed" figure counted only the audited non-auto cells; the ⚡ cells were exempted, so they were never in the denominator. Any future ⚡ cell must be checked against Correction 2's question — *does the detector cover the criterion, or only the part the fixer touches?* — before its 🟢 is trusted.
- **Open honesty decision (flagged, not yet actioned — its own task):** in the per-file FileDrawer coverage table, a 🟡 review-lane criterion that ALSO has a pass/fail detector (e.g. 1.1.1: real missing-alt check) currently shows **PASS** when the scan finds nothing. Per this model that over-claims — ACP can't certify a 1.1.1 pass (alt adequacy). The audited position: **a review-lane criterion with no finding should read "no issue found — verify", never a green certified PASS.** Implementing it flips many drawer rows and needs its own careful change; recommended as the next follow-up.
