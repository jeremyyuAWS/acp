# XLSX-IMGTEXT-001 — Text baked into an image

**WCAG:** 1.4.5 Images of Text (Level AA)  
**Severity:** MODERATE  
**Fix mode:** ai-assisted  
**Source:** `api/textchecks.py`

## What it checks

Detects an embedded image appears to contain readable text. text rendered into images cannot be resized, translated, or read by assistive technology. replace with real cell content in xlsx documents. The check targets the specific XML or binary structure that encodes this property so the engine can identify it without running the full document render pipeline.

## Why it matters

Images of Text (1.4.5) requires that text must be real text rather than an image, unless essential. When this requirement is violated, assistive technology users may receive incorrect, misleading, or no information about the content.

## Unit test recipe

```python
from pathlib import Path

def test_xlsx_imgtext_001_flags_violation(tmp_path):
    # Create a minimal xlsx document that violates this rule, run the detector,
    # and assert the finding is emitted.
    # See existing tests in tests/ for the fixture-construction pattern for xlsx.
    pass  # implement with format-specific fixture helpers
```

## Failure modes

- **False negative:** edge cases in the xlsx XML schema may produce findings the detector misses. Report as a bug with the offending file attached.
- **False positive:** borderline cases near the threshold may generate spurious findings. Human review is the final gate for ai-assisted and human-only rules.
