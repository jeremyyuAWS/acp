# PPTX-ALT-001 — Image missing alt text

**WCAG:** 1.1.1 Non-text Content (Level A)  
**Severity:** CRITICAL  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/AltTextRule.cs`

## What it checks

Every `<pic:pic>`/`<p:pic>` on every slide must have a non-empty `descr` on its `<p:cNvPr>`, unless the shape carries the PowerPoint decorative extension (`adec:decorative val="1"`). NOT checked: charts, SmartArt and grouped-shape internals (separate elements), or the *quality* of the description.

## Why it matters

Slides lean on imagery harder than any other format — often the image IS the content. A screen reader hitting an undescribed picture announces "image", leaving the listener with a hole exactly where the point of the slide was.

## Fix mode rationale

**auto** — the engine writes an AI-generated caption from the image bytes into `descr`. XML-attribute-only change; slides render identically.

## Unit test recipe

```python
import zipfile
from lxml import etree

def undescribed_pics(path):
    n = 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                root = etree.fromstring(z.read(name))
                for pr in root.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr"):
                    if not (pr.get("descr") or "").strip():
                        n += 1
    return n

assert undescribed_pics("pptx-alt-missing-image.pptx") > 0    # FAIL
assert undescribed_pics("pptx-compliant.pptx") == 0           # PASS
```

## Failure modes

- **False positive:** Decorative flourishes not marked with the decorative extension (common in files from older PowerPoint versions) are flagged.
- **False negative:** An image inside a group whose group-level cNvPr has a descr passes even if the meaningful inner picture has none.
