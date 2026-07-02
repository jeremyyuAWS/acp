# DOCX-ALT-001 — Image missing alt text

**WCAG:** 1.1.1 Non-text Content (Level A)  
**Severity:** CRITICAL  
**Fix mode:** auto  
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Docx/Rules/AltTextRule.cs`

## What it checks

Every `<w:drawing>` element that contains a `<wp:docPr>` node must have a non-empty `descr` attribute. The check excludes images whose `descr` is explicitly set to an empty string AND whose `title` attribute is `""` with the drawing marked as decorative (which is the correct way to mark a decorative image in Word).

## Why it matters

Screen readers (NVDA, JAWS, VoiceOver) announce the `descr` value when the user's focus reaches an image. Without it, they say "image" or read the filename — giving no information about the content.

## How the engine fixes it (auto)

The engine fills `descr` from a FAITHFUL in-document source, in priority order: the author's own Alt-Text *Title* field, an adjacent "Figure N:" caption paragraph (docx only), or a meaningful (non-generic) shape name. Bare-filename or generic `descr` values ("image.png") are treated as missing and replaced the same way. Images with no faithful source are left untouched and reported for human review — invented alt text is worse than none. (AI captioning from image bytes needs a vision model, which the deployed Ollama text model doesn't provide — this is the honest deterministic subset.) No layout changes occur; only the XML attribute is updated.

## Unit test recipe

```python
from lxml import etree

def make_drawing(descr: str | None) -> etree._Element:
    nsmap = {"wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}
    doc_pr = etree.Element("{%s}docPr" % nsmap["wp"], nsmap=nsmap)
    if descr is not None:
        doc_pr.set("descr", descr)
    return doc_pr

# Should flag: no descr attribute
assert rule.check(make_drawing(None)) == "FAIL"

# Should flag: empty string
assert rule.check(make_drawing("")) == "FAIL"

# Should pass: has content
assert rule.check(make_drawing("Bar chart showing Q4 revenue")) == "PASS"
```

## Failure modes

- **False positive:** decorative images where the author set `descr=""` but did NOT mark the shape as decorative — the engine still flags these. Correct fix: mark as decorative or provide alt text.
- **False negative:** images embedded via OLE (not `<w:drawing>`) are not checked by this rule. Tracked in backlog.
