# pdf.document-language — Document language not declared

**WCAG:** 3.1.1 Language of Page (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `deploy/public/vendor/worker-python/analysers/rules/pdf/document_language.py`

## What it checks

A `/Lang` entry with a plausible BCP 47 code in the document catalog. NOT checked: span-level `/Lang` overrides inside the tag tree, or declaration-vs-content match.

## Why it matters

Voice selection for the whole document — the same stakes as every other format, but PDFs are the most commonly published format of all, so the blast radius is larger.

## Fix mode rationale

**auto** — dominant-script detection over extracted text writes `/Lang` on the catalog.

## Unit test recipe

```python
import pikepdf
with pikepdf.open("pdf-titled-lang.pdf") as pdf:
    assert str(pdf.Root.get("/Lang", "")).strip()
with pikepdf.open("pdf-critical-untagged-no-lang.pdf") as pdf:
    assert not str(pdf.Root.get("/Lang", "")).strip()
```

## Failure modes

- **False positive:** —
- **False negative:** Malformed-but-present codes ("english") pass the presence check; only absence/empty fails.
