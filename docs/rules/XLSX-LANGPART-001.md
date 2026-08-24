# XLSX-LANGPART-001 — Language of parts cannot be declared

**WCAG:** 3.1.2 Language of Parts (Level AA)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `api/office_structure.py`

## What it checks

Detects spreadsheetml rich-text run properties (ct_rprelt) have no language element, so language-of-parts cannot be recorded in the file. text in a language different from the workbook default cannot be marked up and must be re-authored to avoid mispronunciation in xlsx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Language of Parts (3.1.2) requires that passages in a different language must be marked so assistive technology switches pronunciation rules. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_xlsx_langpart_001_flags_violation(tmp_path):
    # Create a minimal xlsx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for xlsx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the xlsx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
