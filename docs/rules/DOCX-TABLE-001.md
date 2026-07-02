# DOCX-TABLE-001 — Table has no header row

**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/TableHeaderRule.cs`

## What it checks

Every `<w:tbl>` must have `<w:tblHeader/>` in the row properties of its first row. NOT checked: layout tables (Word has no reliable data-vs-layout marker, so every table is treated as data), multi-row headers, or row-scope headers.

## Why it matters

With a marked header row, a screen reader announces the column label before each cell ("Quarter: Q3, Revenue: 1.2M"). Without it, users navigating a large table hear bare numbers with no context.

## Fix mode rationale

**auto** — the engine adds `<w:tblHeader/>` to the first row of each unmarked table. First-row-as-header is the overwhelmingly common case; a wrong guess is visible and harmless (announcements name the wrong row but the data is untouched).

## Unit test recipe

```python
import zipfile
from lxml import etree
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

def first_rows_marked(path):
    with zipfile.ZipFile(path) as z:
        doc = etree.fromstring(z.read("word/document.xml"))
    out = []
    for tbl in doc.iter(f"{W}tbl"):
        row = tbl.find(f"{W}tr")
        out.append(row is not None and row.find(f".//{W}tblHeader") is not None)
    return out

assert all(first_rows_marked("docx-compliant.docx"))
assert not all(first_rows_marked("docx-noncompliant.docx"))
```

## Failure modes

- **False positive:** Pure layout tables (used for positioning, not data) are flagged even though headers are meaningless for them.
- **False negative:** A table whose real header is the first *column* (row-scope) passes once the first row is marked, even though the announced labels are wrong.
