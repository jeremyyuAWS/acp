# DOCX-BOOKMARK-001 — Long document has no bookmarks

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** MINOR  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/BookmarksRule.cs`

## What it checks

Documents whose page count (from `docProps/app.xml`) exceeds 10 must contain at least one named, non-hidden `<w:bookmarkStart>`. NOT checked: bookmark coverage or placement quality — one bookmark anywhere satisfies the rule; documents of 10 pages or fewer are exempt.

## Why it matters

In long documents, bookmarks (with heading navigation) are how assistive-technology users jump to a section instead of paging linearly through dozens of pages.

## Fix mode rationale

**auto** — the engine creates bookmarks at each Heading 1/Heading 2, named from the heading text. Additive markup; nothing visible changes in print or layout.

## Unit test recipe

```python
# (page_count, bookmark_names) -> outcome
assert check(8, []) == "PASS"          # short doc exempt
assert check(24, []) == "FAIL"
assert check(24, ["Introduction"]) == "PASS"
```

## Failure modes

- **False positive:** Long documents that are genuinely linear (a novel-style report with no sections) still get flagged.
- **False negative:** Auto-generated bookmark names from vague headings ("Overview", "Misc") satisfy the rule without aiding navigation much.
