# XLSX-ALT-001 — Image missing alt text

**WCAG:** 1.1.1 Non-text Content (Level A)  
**Severity:** CRITICAL  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/AltTextRule.cs`

## What it checks

Every image in `xl/drawings/*.xml` must have a non-empty `descr` on its `<xdr:cNvPr>`, unless the drawing carries the OOXML decorative extension (`adec:decorative val="1"` in `<xdr:cNvPr>`'s `extLst`) — the same shared Office marker Word and PowerPoint use for "Mark as decorative". NOT checked: charts (see the chart-specific oracle corpus file — chart alt lives on the chart part), sparklines, or conditional-format icons.

## Why it matters

Spreadsheets embed logos, flow diagrams and screenshots; without alt text a screen-reader user auditing the workbook has no idea the image exists, let alone what it shows.

## Fix mode rationale

**auto** — The engine fills `descr` from a FAITHFUL in-document source, in priority order: the author's own Alt-Text *Title* field, an adjacent "Figure N:" caption paragraph (docx only), or a meaningful (non-generic) shape name. Bare-filename or generic `descr` values ("image.png") are treated as missing and replaced the same way. Images with no faithful source are left untouched and reported for human review — invented alt text is worse than none. (AI captioning from image bytes needs a vision model, which the deployed Ollama text model doesn't provide — this is the honest deterministic subset.)

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

- **False negative:** Charts without alt text are missed by THIS rule when the drawing anchor itself carries a descr.
