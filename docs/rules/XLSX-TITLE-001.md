# XLSX-TITLE-001 — Document title not set

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/DocumentTitleRule.cs`

## What it checks

`docProps/core.xml` `<dc:title>` must be non-empty — identical mechanics to DOCX-TITLE-001, applied to the workbook. NOT checked: title quality; sheet names are XLSX-SHEET-001's job.

## Why it matters

The workbook title is what's announced on open and shown in the task switcher; "Book1" tells a screen-reader user nothing about which of five open workbooks holds the budget.

## Fix mode rationale

**auto** — derived from the first sheet's name or the most prominent header cell, written to core properties.

## Unit test recipe

```python
# same recipe as DOCX-TITLE-001, against docProps/core.xml in the xlsx zip
assert title_of("xlsx-noncompliant.xlsx") == ""
assert title_of("xlsx-compliant.xlsx") != ""
```

## Failure modes

- **False positive:** Scratch workbooks that will never be published are held to the same bar.
- **False negative:** Boilerplate titles pass.
