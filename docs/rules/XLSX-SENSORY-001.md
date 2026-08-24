# XLSX-SENSORY-001 — Instructions rely on sensory characteristics

**WCAG:** 1.3.3 Sensory Characteristics (Level A)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `api/textchecks.py`

## What it checks

Detects instructions that identify content solely by shape, visual position, size, or sound cannot be understood by users who are blind or deaf. re-word to include a non-sensory alternative in xlsx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Sensory Characteristics (1.3.3) requires that instructions must not rely solely on sensory characteristics (shape, colour, size, position, sound). When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_xlsx_sensory_001_flags_violation(tmp_path):
    # Create a minimal xlsx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for xlsx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the xlsx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
