# PPTX-SPACING-001 — Fixed line spacing may clip text

**WCAG:** 1.4.12 Text Spacing (Level AA)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `api/office_structure.py`

## What it checks

Detects text runs with an exact (fixed) line height setting may clip descenders or clip adjacent lines when a user's os increases text spacing. prefer proportional line spacing over an exact point value in pptx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Text Spacing (1.4.12) requires that text spacing (line height, letter, word, paragraph) must be overridable without loss of content. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_pptx_spacing_001_flags_violation(tmp_path):
    # Create a minimal pptx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for pptx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the pptx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
