# PPTX-HEADLABEL-001 — Slide title placeholder is empty

**WCAG:** 2.4.6 Headings and Labels (Level AA)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `api/office_structure.py`

## What it checks

Detects a slide has a title placeholder that exists but contains no text. an empty title provides no navigation landmark for screen reader users jumping between slides by heading in pptx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Headings and Labels (2.4.6) requires that headings and labels must describe their topic or purpose. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pptx_headlabel_001_flags_violation(tmp_path):
    # Create a minimal pptx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pptx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pptx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
