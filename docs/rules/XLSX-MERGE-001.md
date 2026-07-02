# XLSX-MERGE-001 — Merged cells break navigation

**WCAG:** 1.3.2 Meaningful Sequence (Level A)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/MergedCellsRule.cs`

## What it checks

Finds any `<mergeCell>` elements in the worksheet XML. Merged cells that span more than one row or column are flagged regardless of content.

## Why it matters

Screen readers navigate Excel by cell address. A merged cell spanning A1:C1 means B1 and C1 are unreachable via keyboard navigation — the reader jumps from A1 to D1 with no indication that B1 and C1 exist. This breaks WCAG 1.3.2 (Meaningful Sequence) because the logical structure cannot be determined programmatically.

## Why fix mode is human-only

"Unmerging" a cell requires a layout decision: what goes in each of the previously merged cells? The engine cannot know this without author context.

## Remediation for authors

1. Select the merged cell.
2. **Home → Merge & Center → Unmerge Cells**.
3. Use **Center Across Selection** (Format Cells → Alignment) to achieve the same visual appearance without merging.

## Unit test recipe

```python
import zipfile
from lxml import etree

def merged_ranges(path, sheet="xl/worksheets/sheet1.xml"):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read(sheet))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    return [m.get("ref") for m in root.iter(f"{ns}mergeCell")]

assert merged_ranges("xlsx-noncompliant.xlsx")        # FAIL: has merges
assert not merged_ranges("xlsx-compliant.xlsx")       # PASS: none
```

## Failure modes

- **False positive:** a merged title banner above (not inside) the data range is flagged even though it never intersects cell navigation of the data itself.
- **False negative:** visually simulated merges (adjacent cells with borders removed and text overflowing) pass — no `mergeCell` entry exists to detect.
