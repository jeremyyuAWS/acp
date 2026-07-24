# XLSX-TABLE-NAME-001 — Generic table name

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/TableNameRule.cs`

## What it checks

A formal table's (ListObject) `DisplayName` against Excel's auto-generated default pattern `Table\d+`. NOT checked: header-row presence (XLSX-TABLE-001 owns that), or plain data ranges never formalised as tables.

## Why it matters

A table's name is exposed to assistive technology and formula authors (`=SUM(Table1[Amount])`) as its identity. "Table1", "Table2" tells a screen-reader user nothing about what a table holds — the same problem generic sheet names solve for tabs (XLSX-SHEET-001), one level down.

## Fix mode rationale

**auto** — renames the table from its header row or the sheet's title, mirroring the sheet-rename fixer's approach. Formula references update automatically because Excel tracks table identity, not display text.

## Unit test recipe

```python
assert check(displayName="Table1") == "FAIL"
assert check(displayName="Table42") == "FAIL"
assert check(displayName="QuarterlySalesData") == "PASS"
```

## Failure modes

- **False positive:** A table intentionally left at its default name for a throwaway scratch range gets renamed.
- **False negative:** A table renamed to something equally unhelpful ("Table_final_v2") passes — only default-pattern matching is checked, not name quality.
