# XLSX-TABLE-001 — Data range has no header row

**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/TableHeaderRule.cs`

## What it checks

Every `<table>` part (ListObject) must have `headerRowCount` ≥ 1 (absent defaults to 1 — explicitly setting 0 is the violation). NOT checked: raw data ranges never formalised as tables — the rule cannot see data that isn't marked as a table.

## Why it matters

Formal tables with headers are what make screen-reader spreadsheet navigation viable: the column name is announced with each cell. A headerless ListObject reads as a wall of anonymous values.

## Fix mode rationale

**auto** — sets `headerRowCount="1"` and, if the first row was data, shifts it into the header slot the way Excel's own "My table has headers" toggle does.

## Unit test recipe

```python
assert check(headerRowCount=None) == "PASS"   # OOXML default is 1
assert check(headerRowCount="1") == "PASS"
assert check(headerRowCount="0") == "FAIL"
```

## Failure modes

- **False positive:** A ListObject deliberately created headerless to feed a formula range gets its first data row promoted.
- **False negative:** Plain ranges that LOOK like tables (the most common real-world case) are invisible to this rule.
