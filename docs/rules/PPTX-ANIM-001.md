# PPTX-ANIM-001 — Animation interferes with reading

**WCAG:** 2.1.1 Keyboard (Level A)  
**Severity:** MODERATE  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/AnimationOrderRule.cs`

## What it checks

The slide's timing tree (`<p:timing>`) is scanned for effects that remove content (exit effects) or reorder it after narration starts. NOT checked: motion-only emphasis effects, transition effects between slides, or flash-rate limits (a separate seizure-safety concern outside this rule).

## Why it matters

Assistive technology reads the slide's DOM once; animation that hides or resequences shapes means the audio narration and the visible slide diverge — a sighted-vs-AT information gap.

## Fix mode rationale

**human-only** — whether an exit animation destroys meaning or is cosmetic depends entirely on the content; the engine can only point at the effect.

## Unit test recipe

```python
assert check(effects=[]) == "PASS"
assert check(effects=["entrance"]) == "PASS"
assert check(effects=["exit"]) == "FAIL"
```

## Failure modes

- **False positive:** An exit effect on a purely decorative shape is flagged.
- **False negative:** An entrance effect that buries earlier content underneath passes — occlusion is not computed.
