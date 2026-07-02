# PPTX-TABLE-001 — Table has no header row

**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/TableHeaderRule.cs`

## What it checks

Every `<a:tbl>` must have `firstRow="1"` set in its table properties (`<a:tblPr>`), the OOXML marker PowerPoint uses for "header row" styling AND semantics. NOT checked: whether the first row actually contains labels, multi-level headers, or tables pasted as images (those fall under PPTX-ALT-001).

## Why it matters

As with Word tables: the header-row flag is what lets a screen reader announce column labels while the user arrows through cells, instead of a stream of context-free values.

## Fix mode rationale

**auto** — sets `firstRow="1"` on unmarked tables. This can subtly change the table's visual banding (header styling activates), which is the known cosmetic trade-off of the fix.

## Unit test recipe

```python
assert check(tblPr_firstRow="1") == "PASS"
assert check(tblPr_firstRow="0") == "FAIL"
assert check(tblPr_firstRow=None) == "FAIL"
```

## Failure modes

- **False positive:** Matrix-style tables with no natural header row get the flag (and the fix's banding).
- **False negative:** A marked first row full of merged decorative cells passes despite announcing nothing useful.
