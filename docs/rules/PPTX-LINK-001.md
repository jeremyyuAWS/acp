# PPTX-LINK-001 — Link text not descriptive

**WCAG:** 2.4.4 Link Purpose (In Context) (Level A)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/LinkPurposeRule.cs`

## What it checks

Display text of hyperlink runs (`<a:hlinkClick>`) against the same generic-phrase deny-list and bare-URL pattern as DOCX-LINK-001. NOT checked: destination validity, or shape-level links whose "text" is the shape's alt text.

## Why it matters

Identical rationale to Word links: the links list a screen reader offers is only as useful as the link texts in it.

## Fix mode rationale

**ai-assisted** — drafted replacement text goes to the HITL queue; wording on a slide is even more editorially sensitive than in a document.

## Unit test recipe

```python
assert check("click here") == "FAIL"
assert check("www.example.com") == "FAIL"
assert check("Session recording (45 min)") == "PASS"
```

## Failure modes

- **False positive:** Deliberately terse CTA button text ("Go") is flagged.
- **False negative:** Misleading descriptive text passes — destinations are never fetched.
