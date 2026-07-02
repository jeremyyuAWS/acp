# PPTX-CONTRAST-001 — Insufficient colour contrast

**WCAG:** 1.4.3 Contrast (Minimum) (Level AA)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/ColourContrastRule.cs`

## What it checks

Resolved text colour (run properties → placeholder → layout → master theme) against the effective slide background must meet 4.5:1 (3:1 for text ≥18pt, or ≥14pt bold). NOT checked: text over photos/gradients (background colour is not computable — reported as SKIP, not FAIL), WordArt, or text inside embedded objects.

## Why it matters

Low-contrast slide text is unreadable on projectors and for low-vision viewers — the two audiences slides exist for. This is the classic "looked fine on my monitor" failure.

## Fix mode rationale

**human-only** — recolouring text changes the deck's design system; the right fix might be darkening text, changing the background, or updating the theme. That's a design decision, so the engine only reports the measured ratio.

## Unit test recipe

```python
assert ratio("#767077", "#FFFFFF") >= 4.5          # passes AA
assert ratio("#9a948f", "#FFFFFF") < 4.5           # fails normal text
assert check(size_pt=20, ratio=3.2) == "PASS"      # large-text threshold
```

## Failure modes

- **False positive:** Text atop a solid shape whose colour differs from the slide background can be measured against the wrong layer.
- **False negative:** Text over images is skipped entirely — genuinely illegible white-on-light-photo text is never flagged.
