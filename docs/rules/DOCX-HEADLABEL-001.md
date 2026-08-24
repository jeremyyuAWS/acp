# DOCX-HEADLABEL-001 — Heading or label is not descriptive

**WCAG:** 2.4.6 Headings and Labels (Level AA)  
**Severity:** MODERATE  
**Fix mode:** auto  
**Source:** `api/office_structure.py`

## What it checks

Detects every heading must clearly describe the topic of its section. vague or empty headings (e.g. 'section 1', 'untitled') prevent screen reader users from understanding the document's structure at a glance in docx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Headings and Labels (2.4.6) requires that headings and labels must describe their topic or purpose. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_docx_headlabel_001_flags_violation(tmp_path):
    # Create a minimal docx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for docx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the docx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
