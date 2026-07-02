# DOCX-TITLE-001 — Document title not set

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/DocumentTitleRule.cs`

## What it checks

`docProps/core.xml` must contain a `<dc:title>` element with non-whitespace text. NOT checked: whether the title is *meaningful* (a title of "Document1" passes), and the filename is never treated as a substitute title.

## Why it matters

Screen readers announce the document title when the file opens and when switching between windows. Without one, users hear the raw filename — often a cryptic export name that says nothing about the content.

## Fix mode rationale

**auto** — the engine derives a title from the first Heading 1 (or the first non-empty paragraph) and writes it to `<dc:title>`. Purely additive metadata; no body content changes, so no human review is needed.

## Unit test recipe

```python
import zipfile
from lxml import etree

def title_of(path):
    with zipfile.ZipFile(path) as z:
        core = etree.fromstring(z.read("docProps/core.xml"))
    t = core.find(".//{http://purl.org/dc/elements/1.1/}title")
    return (t.text or "").strip() if t is not None else ""

assert title_of("docx-noncompliant.docx") == ""    # FAIL
assert title_of("docx-compliant.docx") != ""       # PASS
```

## Failure modes

- **False positive:** A deliberately untitled template file is still flagged — there is no way to mark "intentionally untitled" in OOXML.
- **False negative:** A whitespace-only or boilerplate title ("Document", "Untitled") passes; the rule checks presence, not quality.
