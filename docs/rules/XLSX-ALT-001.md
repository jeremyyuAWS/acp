# XLSX-ALT-001 — Image missing alt text

**WCAG:** 1.1.1 Non-text Content (Level A)  
**Severity:** CRITICAL  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/AltTextRule.cs`

## What it checks

Every image in `xl/drawings/*.xml` must have a non-empty `descr` on its `<xdr:cNvPr>`. NOT checked: charts (see the chart-specific oracle corpus file — chart alt lives on the chart part), sparklines, or conditional-format icons.

## Why it matters

Spreadsheets embed logos, flow diagrams and screenshots; without alt text a screen-reader user auditing the workbook has no idea the image exists, let alone what it shows.

## Fix mode rationale

**auto** — AI caption written into `descr`, same mechanism as the other formats.

## Unit test recipe

```python
import zipfile
from lxml import etree

def undescribed(path):
    n = 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("xl/drawings/drawing"):
                for pr in etree.fromstring(z.read(name)).iter(
                        "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}cNvPr"):
                    if not (pr.get("descr") or "").strip():
                        n += 1
    return n

assert undescribed("xlsx-chart-no-alt.xlsx") > 0
assert undescribed("xlsx-compliant.xlsx") == 0
```

## Failure modes

- **False positive:** Decorative divider images (Excel has no decorative marker) are always flagged.
- **False negative:** Charts without alt text are missed by THIS rule when the drawing anchor itself carries a descr.
