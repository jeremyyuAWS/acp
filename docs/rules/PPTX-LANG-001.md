# PPTX-LANG-001 — Document language not declared

**WCAG:** 3.1.1 Language of Page (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/DocumentLanguageRule.cs`

## What it checks

The presentation's default text properties (`ppt/presentation.xml` `defaultTextStyle`) or core properties must declare a BCP 47 language. NOT checked: per-run language overrides on individual slides, or whether the declaration matches the actual text.

## Why it matters

Same failure mode as any document format: the screen reader's voice/pronunciation engine follows the declared language, and a mismatch turns narration to mush.

## Fix mode rationale

**auto** — dominant-script detection writes the language into the default text style. Deterministic metadata write.

## Unit test recipe

```python
assert check(presentation_lang=None) == "FAIL"
assert check(presentation_lang="") == "FAIL"
assert check(presentation_lang="en-US") == "PASS"
```

## Failure modes

- **False positive:** Rare: a deck of pure imagery with no text still gets a language written, which is harmless.
- **False negative:** Wrong-but-present declarations pass; only absence is detected.
