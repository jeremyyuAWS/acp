# DOCX-HEAD-001 — Heading structure incorrect

**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/HeadingStructureRule.cs`

## What it checks

The sequence of paragraphs styled `Heading 1..9` must never skip a level going down (H1 → H3 without an H2 in between). NOT checked: whether heading text is meaningful, whether the document starts at H1, or outline-level overrides applied via direct formatting.

## Why it matters

Screen reader users navigate long documents by jumping heading-to-heading; the level hierarchy is their table of contents. A skipped level reads as a missing section and breaks the mental model of the document's structure.

## Fix mode rationale

**auto** — the engine re-levels the offending heading to the next expected level (H3 under an H1 becomes H2). Style-only change: the text and its visual prominence via the style's formatting adjust together, and re-validation confirms the sequence.

## Unit test recipe

```python
# Heading levels extracted in document order:
assert check([1, 2, 3, 2]) == "PASS"
assert check([1, 3]) == "FAIL"        # skipped H2
assert check([2, 3]) == "PASS"        # not starting at H1 is out of scope
```

## Failure modes

- **False positive:** Documents that intentionally use, say, H3 styling for a boxed callout under an H1 are re-leveled even though the author wanted the smaller visual.
- **False negative:** Fake headings — bold 18pt body text used as a heading — carry no outline level at all and are invisible to this rule.
