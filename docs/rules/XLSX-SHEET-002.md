# XLSX-SHEET-002 — Sheet name duplicates another sheet

**WCAG:** 2.4.6 Headings and Labels (Level AA)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/SheetNameUniquenessRule.cs`

## What it checks

Sheet names across the whole workbook for case-insensitive duplicates. NOT checked: whether a name matches Excel's generic default pattern (XLSX-SHEET-001 owns that) — two custom, non-default names that happen to collide still fire here.

## Why it matters

Excel itself refuses to save two sheets with the exact same name, but distinct names that differ only by case, or a workbook produced by a tool with looser validation, can still reach a reader with duplicate tabs. A screen-reader user navigating "Data, Data" by name alone can't tell them apart.

## Fix mode rationale

**auto** — appends a disambiguating suffix drawn from the sheet's own content (a date, region, or table name found on it) to the second and later occurrences, the same content-derived-rename technique XLSX-SHEET-001's fixer uses.

## Unit test recipe

```python
assert check(sheet_names=["Q1", "Q2"]) == "PASS"
assert check(sheet_names=["Data", "data"]) == "FAIL"   # case-insensitive collision
assert check(sheet_names=["Report", "Report", "Report"]) == "FAIL"  # 2nd and 3rd flagged
```

## Failure modes

- **False positive:** none identified — any true name collision is genuinely ambiguous to a screen-reader user.
- **False negative:** External workbooks referencing a renamed sheet by its old name break, the same known risk XLSX-SHEET-001's fixer carries.
