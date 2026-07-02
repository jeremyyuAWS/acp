# DOCX-LANGPART-001 — Language of parts not set

**WCAG:** 3.1.1 Language of Page (Level A)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/LanguageOfPartsRule.cs`

## What it checks

Runs whose text script clearly differs from the document's primary language must carry their own `<w:lang>` override. NOT checked: same-script language switches (English → Dutch is undetectable without dictionaries), or single foreign words shorter than the detector's minimum span.

## Why it matters

A screen reader keeps its primary voice through untagged foreign passages — French read with English pronunciation rules is garbled audio for the listener (WCAG 3.1.2 territory, surfaced under the 3.1.1 rubric key).

## Fix mode rationale

**human-only** — deciding what is genuinely another language versus a proper noun, product name, or quotation is a judgment call; script-based detection drafts nothing safe enough to auto-apply.

## Unit test recipe

```python
# runs = [(text, lang_override)]
assert check([("Hello world", None)], primary="en-US") == "PASS"
assert check([("Bonjour le monde", None)], primary="en-US") == "FAIL"
assert check([("Bonjour le monde", "fr-FR")], primary="en-US") == "PASS"
```

## Failure modes

- **False positive:** Proper nouns and brand names in a foreign script (e.g. a Greek company name) are flagged though tagging them is optional.
- **False negative:** Latin-script language switches (English document quoting Spanish) pass — script detection cannot separate them.
