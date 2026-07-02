# XLSX-LANG-001 — Document language not declared

**WCAG:** 3.1.1 Language of Page (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/DocumentLanguageRule.cs`

## What it checks

A declared language for the workbook's default text — read from the theme/styles parts. NOT checked: per-cell language (OOXML spreadsheets have no per-cell language model worth checking), or declaration-vs-content mismatch.

## Why it matters

Pronunciation-engine selection, as in every other format — cell-by-cell narration in the wrong voice is exhausting to follow.

## Fix mode rationale

**auto** — dominant-script detection over cell text, written once at workbook level.

## Unit test recipe

```python
assert check(lang=None) == "FAIL"
assert check(lang="en-US") == "PASS"
```

## Failure modes

- **False positive:** Numeric-only workbooks still get a language written (harmless).
- **False negative:** Wrong-but-present declarations pass.
