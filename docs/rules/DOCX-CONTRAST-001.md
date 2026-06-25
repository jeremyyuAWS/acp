# DOCX-CONTRAST-001 — Insufficient colour contrast

**WCAG:** 1.4.3 Contrast (Minimum) (Level AA)  
**Severity:** SERIOUS  
**Fix mode:** human-only  
**Source:** `DigitalA11y.Analysers.DotNet/Rules/Docx/ContrastRule.cs`

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
