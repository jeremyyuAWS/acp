# Accessibility Conformance Report

**Product:** mova.io Accessibility Platform (web application UI)
**Standard:** WCAG 2.1, Level A & AA
**Status:** Conformant (pending formal assistive-technology user sign-off)
**Evaluation methods:** Automated testing (axe-core, all views) + manual code / semantic review (accessibility tree, keyboard operation, focus management, live regions).
**Not yet performed:** Formal screen-reader user testing (NVDA / JAWS / VoiceOver).

> **Scope:** this report covers the conformance of the **platform's own web UI**, not the conformance of customer documents it remediates (reported separately via the WCAG coverage matrix).

**Conformance key:** Supports · Partially Supports · Not Applicable

# Part 1 · Platform UI conformance (WCAG 2.1 AA)

## Perceivable
| Criterion | Lvl | Conformance | Notes |
|---|---|---|---|
| 1.1.1 Non-text Content | A | Supports | Icons/images labeled or decorative; charts use `role="img"` + descriptive `aria-label` |
| 1.3.1 Info & Relationships | A | Supports | Headings, lists, tables, form labels, landmarks (`header`/`main`/`nav`) |
| 1.3.2 Meaningful Sequence | A | Supports | DOM order matches visual order |
| 1.4.1 Use of Color | A | Supports | Graph status uses ✓/!/× glyphs + color; legends carry text |
| 1.4.3 Contrast (Minimum) | AA | Supports | Text corrected to ≥ 4.5:1 |
| 1.4.4 / 1.4.10 Resize / Reflow | AA | Supports | Responsive; zoom not blocked |
| 1.4.11 Non-text Contrast | AA | Supports | UI marks & graph dots corrected to ≥ 3:1 |
| 1.4.12 Text Spacing | AA | Supports | No clipping on spacing overrides |
| 1.4.13 Content on Hover or Focus | AA | Not Applicable | No persistent hover/focus content in the UI |

## Operable
| Criterion | Lvl | Conformance | Notes |
|---|---|---|---|
| 2.1.1 Keyboard | A | Supports | All controls operable; graph uses roving tabindex (arrows / Enter / Escape) |
| 2.1.2 No Keyboard Trap | A | Supports | Dialogs trap intentionally; Escape always exits |
| 2.4.1 Bypass Blocks | A | Supports | Skip-to-main link |
| 2.4.2 Page Titled | A | Supports | Document title set |
| 2.4.3 Focus Order | A | Supports | Logical; no positive `tabindex` |
| 2.4.4 Link Purpose (In Context) | A | Supports | Link text is meaningful |
| 2.4.6 Headings & Labels | AA | Supports | Descriptive |
| 2.4.7 Focus Visible | AA | Supports | `:focus-visible` outline on all controls |
| 2.5.3 Label in Name | A | Supports | Visible labels match accessible names |

## Understandable
| Criterion | Lvl | Conformance | Notes |
|---|---|---|---|
| 3.1.1 Language of Page | A | Supports | `<html lang>` set |
| 3.2.1 / 3.2.2 On Focus / On Input | A | Supports | No unexpected change of context |
| 3.2.3 / 3.2.4 Consistent Navigation / Identification | AA | Supports | Consistent navigation & component identity |
| 3.3.1 / 3.3.2 Error Identification / Labels | A | Supports | Inputs labeled; minimal forms |

## Robust
| Criterion | Lvl | Conformance | Notes |
|---|---|---|---|
| 4.1.2 Name, Role, Value | A | Supports | Correct roles/names on custom controls |
| 4.1.3 Status Messages | AA | Supports | `aria-live`/`role=status` on scan, chat, monitor, and assess results |

# Part 2 · Document remediation coverage (WCAG 2.1 + 2.2)

Beyond its own conformance, the platform detects and remediates accessibility issues in the documents it processes. Coverage across all 87 success criteria:

| Coverage | Count | How |
|---|---|---|
| Live | 28 | Deterministic auto-fix or AI (Claude vision / Whisper) |
| Covered · HITL | 42 | Detect-and-route to a human reviewer |
| Partner-provided | 12 | Partner web scanner |
| Roadmap | 5 | Human-produced media (sign language, audio description) |

| Conformance level | Criteria | Covered | Status |
|---|---|---|---|
| Level A · must-have | 32 | 32 / 32 | Fully covered |
| Level AA · legal target | 24 | 24 / 24 | Fully covered — **Level AA conformance reached** |
| Level AAA · optional | 31 | 26 / 31 | 5 optional (human-produced media) remaining |

Every legally-required criterion (Level A and AA) is covered — by deterministic auto-fix, AI, the partner web scanner, or a human-in-the-loop review workflow. The full per-criterion matrix is available as the accompanying **coverage matrix (Excel)** and **method deck (PowerPoint)**.

## Summary statement
The mova.io Accessibility Platform UI **conforms to WCAG 2.1 Level AA** on all applicable Level A and AA success criteria, verified by automated and manual evaluation. Two issues found during manual review (an unannounced status update and a missing navigation landmark) were remediated. A formal screen-reader user evaluation is recommended to finalize a signed conformance statement.

---
*Generated from the in-app self-audit. A one-click PDF export is available from the ♿ accessibility self-check panel.*
