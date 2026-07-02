# PPTX-ORDER-001 — Reading order undefined

**WCAG:** 1.3.2 Meaningful Sequence (Level A)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/ReadingOrderRule.cs`

## What it checks

Reads the `<p:sp>` (shape) order in the slide XML and compares it against the visual bounding boxes of each shape. If the XML order does not match a plausible top-to-bottom, left-to-right reading order, the rule fires.

A slide where PowerPoint's default "auto" tab order is in place (shapes ordered by insertion time, not position) is flagged unless that order happens to match the visual order.

## Why fix mode is human-only

Reading order requires understanding the author's intent. A two-column layout has an ambiguous reading order (column-first or row-first), and a deliberately non-linear slide (e.g. a diagram with callouts) may be correct even if the boxes don't go top-to-bottom. The engine can detect the mismatch but cannot safely reorder shapes.

## Remediation steps for authors

1. Open the slide in PowerPoint.
2. Go to **Home → Arrange → Selection Pane**.
3. Drag shapes in the Selection Pane so the order (bottom to top in the pane) matches the intended reading sequence.
4. Re-save and re-scan to verify.

## Why it matters

A screen reader announces shapes in XML (tab) order, not visual order. When the two diverge, the listener hears the slide scrambled — conclusion before premise, labels detached from the diagram they name — while sighted viewers see a perfectly sensible layout. The divergence is invisible to the author until someone hears it.

## Unit test recipe

```python
# shapes as (xml_index, bbox_top, bbox_left)
assert check([(0, 100, 100), (1, 200, 100)]) == "PASS"   # XML order matches visual
assert check([(0, 200, 100), (1, 100, 100)]) == "FAIL"   # bottom shape read first
```

## Failure modes

- **False positive:** deliberately non-linear slides (a central diagram with orbiting callouts) can be flagged although the author's order is the meaningful one.
- **False negative:** a two-column slide read column-first passes the plausibility check even when the author intended row-first.
