# XLSX-SHEET-001 — Generic sheet name

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/SheetNameRule.cs`

## What it checks

Worksheet names against the default-name pattern `Sheet\d+` (and localized equivalents the engine knows). NOT checked: name quality beyond non-default (a sheet named "x" passes), or hidden sheets (XLSX-HIDDEN-001 owns those).

## Why it matters

Sheet tabs are the workbook's top-level navigation. A screen-reader user choosing between "Sheet1, Sheet2, Sheet3" must open each to learn what it holds; named tabs make the choice instant.

## Fix mode rationale

**auto** — renames the sheet from its most prominent content (title cell / table name), e.g. "Sheet2" → "Q3 Budget". References update automatically because Excel formulas track sheet identity, not display text — but see failure modes.

## Unit test recipe

```python
assert check("Sheet1") == "FAIL"
assert check("Tabelle1") == "FAIL"    # localized default
assert check("Q3 Budget") == "PASS"
```

## Failure modes

- **False positive:** A workbook intentionally using positional sheets (an exported per-day dump) gets renamed.
- **False negative:** External workbooks referencing this file by sheet NAME (`'[book.xlsx]Sheet1'!A1`) break after a rename — the engine can't see external links, so the rule's auto-fix carries this known risk.
