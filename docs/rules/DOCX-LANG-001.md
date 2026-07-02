# DOCX-LANG-001 — Document language not declared

**WCAG:** 3.1.1 Language of Page (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/DocumentLanguageRule.cs`

## What it checks

`word/settings.xml` (`<w:themeFontLang>`) or the default run properties in `word/styles.xml` must declare a BCP 47 primary language (`<w:lang w:val>`). NOT checked: whether the declared language matches the actual body text, or per-run language overrides (that is DOCX-LANGPART-001).

## Why it matters

Screen readers pick their pronunciation engine from the document language. An English voice reading German text (or vice versa) is close to unintelligible for the listener.

## Fix mode rationale

**auto** — the engine detects the dominant script of the body text and writes the matching `w:lang` value. Deterministic metadata write; a wrong auto-detection is caught at re-validation.

## Unit test recipe

```python
import zipfile
from lxml import etree
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

def lang_of(path):
    with zipfile.ZipFile(path) as z:
        styles = etree.fromstring(z.read("word/styles.xml"))
    el = styles.find(f".//{W}lang")
    return el.get(f"{W}val") if el is not None else None

assert lang_of("docx-noncompliant.docx") in (None, "")   # FAIL
assert lang_of("docx-compliant.docx")                    # PASS
```

## Failure modes

- **False positive:** Documents that are genuinely multilingual with no dominant language still get a single primary tag — technically correct per WCAG, but the per-part tagging matters more there.
- **False negative:** A wrong-but-present declaration (`en-US` on a French document) passes this rule; only absence is detected.
