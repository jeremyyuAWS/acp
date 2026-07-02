# DOCX-CONTRAST-001 — Insufficient colour contrast

**WCAG:** 1.4.3 Contrast (Minimum) (Level AA)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/ColourContrastRule.cs`

## What it checks

For every paragraph run that has explicit text colour (`<w:color>`) and background shading (`<w:shd>`), the rule computes the WCAG relative luminance contrast ratio between the foreground and background RGB values. Contrast below 4.5:1 for normal text (below 3:1 for large text ≥ 18pt or 14pt bold) is flagged.

Runs that use automatic colour (no `<w:color>`) are not checked — their contrast depends on the viewer's theme, which is outside the document.

## Why fix mode is human-only

Choosing a replacement colour that meets contrast AND preserves brand identity is a design decision. The engine surfaces the exact failing pair and the required ratio; the author or designer picks the replacement.

## What the finding includes

- Foreground hex, background hex
- Measured ratio (e.g. `2.8:1`)
- Required ratio (`4.5:1` or `3:1` for large text)
- Paragraph text excerpt (first 60 characters)

## Why it matters

Low-contrast text is the single most common barrier for low-vision readers — and it degrades further on projectors, low-brightness screens, and printed copies. 4.5:1 is the WCAG AA floor below which a substantial share of readers simply cannot make the text out.

## Unit test recipe

```python
# WCAG relative-luminance ratio, as the rule computes it
assert ratio("#000000", "#FFFFFF") == 21.0
assert ratio("#767077", "#FFFFFF") >= 4.5      # PASS at normal size
assert ratio("#9a948f", "#FFFFFF") < 4.5       # FAIL at normal size
assert check(fg="#9a948f", bg="#FFFFFF", size_pt=18) == "PASS"  # large-text 3:1
```

## Failure modes

- **False positive:** text over a shaded run whose EFFECTIVE background comes from a table-cell or page fill the rule doesn't resolve — the measured pair isn't what the reader sees.
- **False negative:** automatic-colour runs (no `<w:color>`) are skipped entirely, so a document whose theme yields low contrast passes.
