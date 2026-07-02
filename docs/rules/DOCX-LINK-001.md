# DOCX-LINK-001 — Link text not descriptive

**WCAG:** 2.4.4 Link Purpose (In Context) (Level A)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/LinkPurposeRule.cs`

## What it checks

The display text of every `<w:hyperlink>` is tested against a deny-list of generic phrases (click here, read more, more, link, this page…) and a bare-URL pattern. NOT checked: whether descriptive text actually matches the destination, or repeated identical link texts pointing at different targets.

## Why it matters

Screen reader users pull up a links list to skim a document. Ten links all announcing "click here" are indistinguishable — the destination is only knowable by leaving the list and reading the surrounding text.

## Fix mode rationale

**ai-assisted** — the engine drafts replacement text from the destination URL and surrounding sentence, but wording is judgment ("2026 benefits enrollment form" vs "HR portal"), so the draft routes to the HITL queue for sign-off before it's applied.

## Unit test recipe

```python
assert check("click here") == "FAIL"
assert check("https://example.com/x?y=1") == "FAIL"    # bare URL
assert check("2026 benefits enrollment form") == "PASS"
```

## Failure modes

- **False positive:** Short-but-clear texts like "map" or a product name that resembles a deny-list phrase can be flagged.
- **False negative:** Descriptive-sounding text that lies about the destination passes — the rule never fetches the target.
