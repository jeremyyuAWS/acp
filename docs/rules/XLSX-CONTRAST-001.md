# XLSX-CONTRAST-001 — Insufficient colour contrast

**WCAG:** 1.4.3 Contrast (Minimum) (Level AA)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `api/office_structure.py`

## What it checks

Detects cell text colour against its background must meet the 4.5:1 minimum contrast ratio for normal-sized text (3:1 for large text ≥18pt or 14pt bold) in xlsx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Contrast (Minimum) (1.4.3) requires that text and images of text must meet a 4.5:1 contrast ratio (3:1 for large text). When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_xlsx_contrast_001_flags_violation(tmp_path):
    # Create a minimal xlsx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for xlsx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the xlsx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
