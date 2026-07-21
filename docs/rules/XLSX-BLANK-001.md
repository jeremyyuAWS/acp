# XLSX-BLANK-001 — Blank worksheet

**WCAG:** 1.3.2 Meaningful Sequence (Level A)
**Severity:** MODERATE
**Fix mode:** human-only
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/BlankWorksheetRule.cs`

## What it checks

Every visible sheet is checked for live cell content — actual cell values or formulas, walked cell-by-cell, never the sheet's cached dimension/"used range" record (that record reflects the historical maximum extent a writer ever touched and stays inflated even after every cell in it has been cleared). A sheet with no live cell content is still not flagged if it anchors a chart (`GraphicFrame`) or image (`Picture`) — a chart-only dashboard sheet is not blank. Hidden and very-hidden sheets are skipped entirely: no user ever tabs to one, so a blank hidden sheet has no navigation exposure to flag.

## Why it matters

A visible, empty sheet tab is a dead stop for a screen reader user tabbing through the workbook — no content, no explanation for why the tab exists. Sighted users skim past it visually in a fraction of a second; assistive-technology users must fully navigate into it to discover there's nothing there.

## Fix mode rationale

**human-only** — the correct fix is either "delete the sheet" or "add the content that was supposed to be there," and only the author knows which. The engine can detect emptiness but not intent.

## Unit test recipe

```python
assert check(sheets=[("Data", "visible", has_cells=True)]) == "PASS"
assert check(sheets=[("Notes", "visible", has_cells=False)]) == "FAIL"
assert check(sheets=[("Dashboard", "visible", has_cells=False, has_chart=True)]) == "PASS"
assert check(sheets=[("Scratch", "hidden", has_cells=False)]) == "PASS"
```

See `tests/test_xlsx_blank_worksheet.py` for the full fixture (visible data sheet, genuinely blank sheet, chart-only sheet, picture-only sheet, a sheet with a cleared cell whose dimension record stays stale, and a hidden blank sheet) run through the real .NET engine.

## Failure modes

- **False positive:** A sheet holding only a pivot table (no literal cell values in the pivot's own range, cache-driven) could be misread as blank — not currently exempted, same open question as blank-sheet's own WCAG mapping (it is authoring hygiene, not a direct success-criterion violation, filed under 1.3.2 by the same convention as XLSX-HIDDEN-001/XLSX-MERGE-001).
- **False negative:** A sheet with only a cell comment, defined name, or conditional-formatting rule and no literal values reads as blank, even though Excel's UI would show *something* on it.
