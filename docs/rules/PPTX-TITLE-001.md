# PPTX-TITLE-001 — Slide title not set

**WCAG:** 2.4.2 Page Titled (Level A)  
**Severity:** SERIOUS  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Pptx/Rules/SlideTitleRule.cs`

## What it checks

Every slide must contain a placeholder of type `title` (or `ctrTitle`) with non-empty text. NOT checked: text boxes styled to look like titles (only real Title placeholders count), uniqueness of titles across slides, or hidden slides.

## Why it matters

Slide titles are the unit of navigation: assistive technology announces them when moving between slides, and they form the presentation's outline. An untitled slide is announced as "Slide 7" — position, not meaning.

## Fix mode rationale

**auto** — the engine inserts a title from the slide's most prominent text (largest top-most text run) into the layout's Title placeholder, or adds an off-slide title when nothing suitable exists — the standard "invisible title" technique.

## Unit test recipe

```python
# per-slide: does a Title placeholder with text exist?
assert check(slide_with(title="Q3 results")) == "PASS"
assert check(slide_with(title=None)) == "FAIL"
assert check(slide_with(textbox_looking_like_title="Q3")) == "FAIL"  # not a placeholder
```

## Failure modes

- **False positive:** Section-divider slides that are intentionally a single full-bleed image still need a (possibly off-slide) title.
- **False negative:** Duplicate titles ("Agenda" ×5) pass, though they make outline navigation ambiguous.
