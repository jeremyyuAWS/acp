# PPTX-TITLE-002 — Slide title duplicates another slide

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/SlideTitleUniquenessRule.cs`

## What it checks

Every slide's Title placeholder text against every earlier slide's, case-insensitively. NOT checked: whether a title is present at all (PPTX-TITLE-001 owns that) — this rule only compares titles that already exist and are non-empty.

## Why it matters

Slide titles are the outline assistive technology reads when jumping between slides. Five slides all titled "Agenda" are individually compliant with "has a title" but collectively useless for outline navigation — a screen-reader user can't tell which "Agenda" is which.

## Fix mode rationale

**auto** — appends a disambiguating suffix drawn from the slide's own body content (its first bullet, or a section number) to the second and later occurrences sharing a title — the same content-derived-rename technique the sheet-uniqueness fixer uses.

## Unit test recipe

```python
assert check(titles=["Overview", "Q3 Results"]) == "PASS"
assert check(titles=["Agenda", "agenda"]) == "FAIL"    # case-insensitive, 2nd slide flagged
assert check(titles=["Agenda", "Agenda", "Agenda"]) == "FAIL"  # 2nd and 3rd flagged
```

## Failure modes

- **False positive:** Intentionally repeated section-divider titles ("Break") across a long deck get flagged even though a human reviewer might judge the repetition harmless.
- **False negative:** Titles that a human would call functionally identical but that differ in wording ("Q3 Results" vs. "Third Quarter Results") pass — only exact (trimmed, case-insensitive) string matches are caught.
