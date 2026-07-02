# pdf.reading-order — Reading order undefined

**WCAG:** 1.3.2 Meaningful Sequence (Level A)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `deploy/public/vendor/worker-python/analysers/rules/pdf/reading_order.py`

## What it checks

For each page, the sequence of text in the tag tree is compared against the geometric top-to-bottom / column order of the rendered text; large divergences fail. NOT checked: pages without tags (SKIP — owned by `pdf.tagged`), right-to-left scripts' column conventions, or tables (cell order is legitimately non-geometric).

## Why it matters

A screen reader follows the tag order, not the visual layout. A two-column PDF tagged in print order reads line one of column one, then line one of column two — interleaved nonsense.

## Fix mode rationale

**human-only** — correct order for sidebars, pull quotes and captions is editorial intent; automated re-ordering can silently destroy meaning, so the engine only reports the mismatch score.

## Unit test recipe

```python
# order pairs: (tag_sequence_index, geometric_index)
assert divergence([(0,0), (1,1), (2,2)]) == 0          # PASS
assert divergence([(0,3), (1,4), (2,0)]) > THRESHOLD   # FAIL
```

## Failure modes

- **False positive:** Intentional non-linear order (a caption tagged with its figure, ahead of body text) can exceed the divergence threshold.
- **False negative:** Locally swapped lines within a paragraph fall under the threshold and pass.
