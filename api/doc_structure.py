"""Document STRUCTURE surfaced as review evidence — the heading outline of a docx, so a heading
finding (1.3.1 / 2.4.6) shows the real before → corrected outline instead of a generic note.

Read-only, deterministic, docx/OOXML-only (like geometry is pptx/xlsx-only): a PDF exposes heading
PRESENCE, not an extractable outline. Honesty (ADR 0016): the "before" is the document's ACTUAL
styled headings in document order; the "after" is a deterministic never-skip renumber of those SAME
headings (one H1, no level jump greater than +1) — no fabricated tree, no invented headings, the
same texts throughout. Imports office_structure's regexes so the parse matches the detector exactly;
importing a rule-path module is fine (only EDITING one triggers the matrix guard).
"""
from __future__ import annotations

import io
import zipfile

_MIN_HEADINGS = 2   # a lone heading has no outline to show


def corrected_levels(levels: list[int]) -> list[int]:
    """Never-skip renumber: a single H1, and each heading at most one level deeper than the previous.
    Deterministic — same input levels → same output — the monotonic nesting WCAG expects."""
    out: list[int] = []
    prev = 0
    for lv in levels:
        c = 1 if prev == 0 else min(int(lv), prev + 1)
        out.append(max(1, min(c, 6)))
        prev = out[-1]
    return out


def heading_outline(data: bytes, ext: str):
    """The styled-heading outline of a docx as {"before":[{level,text}], "after":[{level,text}]}, or
    None when this isn't a docx, has fewer than two headings, or already nests correctly (nothing to
    show). The `after` carries the SAME heading texts, only their levels corrected."""
    if (ext or "").lower().lstrip(".") != "docx" or not data:
        return None
    import office_structure as _os
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            doc = _os._read(zf, "word/document.xml") or ""
    except Exception:
        return None
    headings: list[tuple[int, str]] = []
    for para in _os._PARA.findall(doc):
        m = _os._HEADING_STYLE.search(para)
        if not m:
            continue
        level = max(1, min(int(m.group(1)), 6))
        text = " ".join(t for t in _os._WT.findall(para) if t.strip()).strip()
        headings.append((level, text))
    if len(headings) < _MIN_HEADINGS:
        return None
    levels = [lv for lv, _ in headings]
    fixed = corrected_levels(levels)
    if fixed == levels:                       # already a clean outline — nothing to correct
        return None
    before = [{"level": lv, "text": t} for lv, t in headings]
    after = [{"level": c, "text": t} for c, (_, t) in zip(fixed, headings)]
    return {"before": before, "after": after}
