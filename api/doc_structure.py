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
import re
import zipfile

_MIN_HEADINGS = 2   # a lone heading has no outline to show

# docx table parsing (office_structure has <w:tbl> matching for column counts, but no row/cell regexes).
# Non-greedy, so nested tables are NOT descended into — a stated limitation, not a fabricated guess.
_TBL = re.compile(r"<w:tbl>(.*?)</w:tbl>", re.S)
_TR = re.compile(r"<w:tr\b.*?</w:tr>", re.S)
_TC = re.compile(r"<w:tc\b.*?</w:tc>", re.S)
_TBLHEADER = re.compile(r"<w:tblHeader\b")
_MAX_TABLES, _MAX_ROWS, _MAX_COLS = 3, 8, 8   # this is evidence, not a full dump — caps + reports truncation


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


def table_structure(data: bytes, ext: str):
    """The tables of a docx as review evidence for a header-association finding (1.3.1): each table's
    cell text as a grid, which row is its header, and whether that row is actually MARKED as a header
    (<w:tblHeader>) — the association a screen reader needs to announce a column header for each data
    cell. Returns {"tables": [...]} or None when this isn't a docx or has no qualifying (multi-row,
    multi-column) table. Real extracted content only — the header ROW is the document's own marked
    header, or (when none is marked) the first row, reported plainly as not-yet-marked."""
    if (ext or "").lower().lstrip(".") != "docx" or not data:
        return None
    import office_structure as _os
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            doc = _os._read(zf, "word/document.xml") or ""
    except Exception:
        return None
    tables = []
    for tbl_inner in _TBL.findall(doc)[:_MAX_TABLES]:
        grid, header_marked, header_row = [], False, None
        for ri, row_xml in enumerate(_TR.findall(tbl_inner)):
            if _TBLHEADER.search(row_xml):
                header_marked = True
                if header_row is None:
                    header_row = ri
            grid.append([" ".join(t for t in _os._WT.findall(c) if t.strip()).strip()
                         for c in _TC.findall(row_xml)])
        if len(grid) < 2 or max((len(r) for r in grid), default=0) < 2:   # a real data table
            continue
        if header_row is None:
            header_row = 0            # the de-facto header a screen reader (and the fix) would use
        truncated = len(grid) > _MAX_ROWS or max(len(r) for r in grid) > _MAX_COLS
        grid = [r[:_MAX_COLS] for r in grid[:_MAX_ROWS]]
        tables.append({"rows": grid, "headerRow": header_row,
                       "headerMarked": header_marked, "truncated": bool(truncated)})
    return {"tables": tables} if tables else None
