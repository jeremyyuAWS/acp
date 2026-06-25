# PPTX-ORDER-001 — Reading order undefined

**WCAG:** 1.3.2 Meaningful Sequence (Level A)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `DigitalA11y.Analysers.DotNet/Rules/Pptx/ReadingOrderRule.cs`

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
