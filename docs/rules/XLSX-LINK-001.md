# XLSX-LINK-001 — Link text not descriptive

**WCAG:** 2.4.4 Link Purpose (In Context) (Level A)
**Severity:** MODERATE
**Fix mode:** human-only
**Source:** `digital-accessibility/DigitalA11y.Analysers.DotNet/Xlsx/Rules/LinkPurposeRule.cs`

## What it checks

Two distinct hyperlink mechanisms, both against the same deny-list of generic phrases (click here, read more, more, link, this link, url…) plus a raw-URL check (`http://`, `https://`, `www.`):

1. **Standard cell hyperlinks** (Insert → Link) — read from the worksheet's own `<hyperlinks>` element, display text resolved from the linked cell's actual value.
2. **Formula-driven links** — `=HYPERLINK(url, [friendly_name])` cells. These never appear in the worksheet's `<hyperlinks>` element at all — a detector that only reads that element (or only `cell.hyperlink` in openpyxl) misses every formula-based link entirely. Detected by matching `HYPERLINK(` in the cell's formula text, with the display text read from the cell's own cached value (the friendly name if given, otherwise the URL Excel displays by default).

Deliberately not re-parsing the formula's arguments for the pass/fail decision — only for a best-effort evidence URL — since formula text can nest quotes and cell references in ways a regex can't reliably unpack.

## Why it matters

Screen reader users pull up a links list to skim a workbook. Ten cells all announcing "click here" (or the raw URL) are indistinguishable — the destination is only knowable by following each one. Formula-based links are just as real a failure mode as standard ones; they're only invisible to a naive checker, not to a screen reader.

## Fix mode rationale

**human-only** — no automated remediation is wired for this rule yet. DOCX and PPTX's link-purpose rule has an AI-assisted drafting lane (destination + surrounding context → a proposed replacement, human-approved before it's written); XLSX doesn't have that lane built. Don't claim `ai-assisted` here until it is — this cell only detects.

## Unit test recipe

```python
assert check(cell_hyperlink_text="click here") == "FAIL"
assert check(cell_hyperlink_text="https://example.com/x?y=1") == "FAIL"   # raw URL
assert check(cell_hyperlink_text="2026 benefits enrollment form") == "PASS"
assert check(formula='=HYPERLINK("https://x.com","click here")') == "FAIL"  # formula-driven, same deny-list
assert check(formula='=HYPERLINK("https://x.com")') == "FAIL"               # no friendly name -> displays the raw URL
```

See `tests/test_xlsx_link_purpose.py` for the full fixture (standard hyperlink with generic text, standard hyperlink with descriptive text, formula-driven link with generic text, formula-driven link with no friendly name, and a plain non-hyperlink cell that must stay silent) run through the real .NET engine.

## Failure modes

- **False positive:** short-but-clear texts like "map" or a product name resembling a deny-list phrase can be flagged, same declared limitation as DOCX/PPTX's link-purpose rule.
- **False negative:** descriptive-sounding text that lies about the destination passes — the rule never fetches the target, same declared limitation as DOCX/PPTX.
- **False negative:** a formula that computes `HYPERLINK(...)` indirectly (e.g. via a helper cell referenced by another formula, or a `LET`/`LAMBDA` wrapper) is not matched — only formulas containing the literal text `HYPERLINK(` are detected.
