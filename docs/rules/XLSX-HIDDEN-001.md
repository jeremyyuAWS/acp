# XLSX-HIDDEN-001 — Hidden content

**WCAG:** 1.3.2 Meaningful Sequence (Level A)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/HiddenContentRule.cs`

## What it checks

Sheets with `state="hidden"`/`veryHidden`, plus hidden rows/columns that contain non-empty cells. NOT checked: zero-height/width rows and columns that are technically visible, filtered-out rows (a view state, not a document state), or whether the hidden content is actually referenced by visible formulas.

## Why it matters

Hidden content splits the audience: formulas and sighted users who know to unhide can reach it, while an assistive-technology user auditing the visible workbook never learns it exists. For a compliance platform, that gap is also a transparency problem.

## Fix mode rationale

**human-only** — hiding is often intentional (scratch calculations, config sheets). Only the author knows whether the content should be exposed, deleted, or documented; the engine reports what is hidden and how much of it holds data.

## Unit test recipe

```python
assert check(sheets=[("Data", "visible")], hidden_cells=0) == "PASS"
assert check(sheets=[("Config", "veryHidden")], hidden_cells=12) == "FAIL"
```

## Failure modes

- **False positive:** Legitimate machinery sheets (lookup tables driving data validation) are flagged on every scan.
- **False negative:** Content "hidden" by white-on-white text or a 0.1pt column passes — only structural hiding is detected.
