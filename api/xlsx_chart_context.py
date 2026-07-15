"""Fallback chart alt-text drafted from the sheet's OWN data — keyless, no vision model.

When a spreadsheet chart has no alt text and the vision model is unavailable (no GPU, no cloud key,
offline), the numbers the chart plots are almost always sitting in cells right beside it. This reads
the nearest data table and composes a concrete draft from it — grounded in the document's own values,
never fabricated. It is offered as a PROPOSAL (the reviewer confirms it against the visible chart), so
a rare wrong table-match is caught on review rather than asserted; that keeps it honest under ADR 0016
while still giving a customer with no AI at all *something* to approve instead of a blank box.

Pure stdlib (zipfile + ElementTree): bytes in, (draft, source) | None out — never raises.
"""
from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

_SS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_to_idx(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _num(s: str) -> str:
    """Trim a float that is really an int ('12.0' -> '12'), leave others ('12.4')."""
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else (f"{f:g}")
    except (TypeError, ValueError):
        return s


def _shared_strings(entries):
    raw = entries.get("xl/sharedStrings.xml")
    if not raw:
        return []
    root = ET.fromstring(raw)
    out = []
    for si in root.findall(f"{{{_SML}}}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{{{_SML}}}t")))
    return out


def _worksheet_for_drawing(entries, drawing_part):
    dn = drawing_part.split("/")[-1]
    for n in entries:
        if not re.match(r"^xl/worksheets/_rels/sheet\d+\.xml\.rels$", n):
            continue
        rroot = ET.fromstring(entries[n])
        for rel in rroot.findall(f"{{{_RELS}}}Relationship"):
            if (rel.get("Target") or "").split("/")[-1] == dn:
                return f"xl/worksheets/{n.split('/')[-1][:-5]}"
    return None


def _anchor_from_row(entries, drawing_part, rid):
    """The 0-based `from` row of the anchor whose picture matches `rid` (blip embed OR cNvPr name)."""
    droot = ET.fromstring(entries[drawing_part])
    for anchor in list(droot):
        pic = anchor.find(f"{{{_SS}}}pic")
        if pic is None:
            continue
        blip = pic.find(f"{{{_SS}}}blipFill/{{{_A}}}blip")
        embed = blip.get(f"{{{_R}}}embed") if blip is not None else None
        cnv = pic.find(f"{{{_SS}}}nvPicPr/{{{_SS}}}cNvPr")
        name = (cnv.get("name") or "").strip() if cnv is not None else None
        if rid == embed or (name and rid == name):
            frm = anchor.find(f"{{{_SS}}}from")
            if frm is not None:
                try:
                    return int(frm.findtext(f"{{{_SS}}}row"))
                except (TypeError, ValueError):
                    return None
    return None


def _read_grid(entries, sheet_part, shared):
    """{(row0, col0): text} for every non-empty cell in the worksheet (0-based indices)."""
    root = ET.fromstring(entries[sheet_part])
    data = root.find(f"{{{_SML}}}sheetData")
    grid = {}
    if data is None:
        return grid
    for row in data.findall(f"{{{_SML}}}row"):
        for c in row.findall(f"{{{_SML}}}c"):
            m = _CELL_RE.match(c.get("r") or "")
            if not m:
                continue
            r0, c0 = int(m.group(2)) - 1, _col_to_idx(m.group(1))
            t = c.get("t")
            if t == "s":                                   # shared string
                v = c.findtext(f"{{{_SML}}}v")
                val = shared[int(v)] if v and v.isdigit() and int(v) < len(shared) else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{_SML}}}t"))
            else:
                val = c.findtext(f"{{{_SML}}}v") or ""
            if str(val).strip():
                grid[(r0, c0)] = str(val).strip()
    return grid


def _tables(grid):
    """Contiguous 2-column data blocks: a header row (two texts) then rows of (label, number).
    Returns [{header_row, label_col, value_col, header:(a,b), rows:[(label,value)…]}]."""
    def is_num(s):
        try:
            float(s); return True
        except (TypeError, ValueError):
            return False
    tables = []
    rows_present = sorted({r for (r, _c) in grid})
    used = set()
    for r in rows_present:
        if r in used:
            continue
        # a header row = two adjacent text cells, the second column's next row is numeric
        cols = sorted(c for (rr, c) in grid if rr == r)
        if len(cols) < 2:
            continue
        a, b = cols[0], cols[1]
        if is_num(grid.get((r, a), "")) or (r + 1, b) not in grid or is_num(grid.get((r, a), "")):
            pass
        # walk data rows: label in col a, numeric in col b
        body = []
        rr = r + 1
        while (rr, a) in grid and (rr, b) in grid and is_num(grid[(rr, b)]):
            body.append((grid[(rr, a)], grid[(rr, b)]))
            used.add(rr)
            rr += 1
        if len(body) >= 2 and not is_num(grid.get((r, a), "x")):
            tables.append({"header_row": r, "header": (grid.get((r, a), ""), grid.get((r, b), "")),
                           "rows": body})
            used.add(r)
    return tables


def draft_from_entries(entries: dict, drawing_part: str, rid: str) -> tuple[str, str] | None:
    """(draft, source) for chart image `drawing_part#rid`, composed from the nearest data table on
    the same sheet, or None when no table is attributable. `entries` is the {part_name: bytes} dict
    remediate_office holds. Never raises."""
    try:
        if drawing_part not in entries:
            return None
        sheet = _worksheet_for_drawing(entries, drawing_part)
        if not sheet or sheet not in entries:
            return None
        from_row = _anchor_from_row(entries, drawing_part, rid)
        if from_row is None:
            return None
        tables = _tables(_read_grid(entries, sheet, _shared_strings(entries)))
        if not tables:
            return None
        # the chart visualises the table nearest it by row (charts sit beside / below their data)
        t = min(tables, key=lambda tb: abs(tb["header_row"] - from_row))
        cat, series = t["header"]
        pairs = ", ".join(f"{lab} {_num(v)}" for lab, v in t["rows"][:12])
        lead = f"Chart of {series} by {cat}" if cat and series else "Chart"
        return (f"{lead}: {pairs}."[:300], "the sheet's own data table")
    except Exception:
        return None


def chart_alt_draft(data: bytes, drawing_part: str, rid: str) -> tuple[str, str] | None:
    """Bytes-in convenience wrapper over draft_from_entries (tests / callers holding raw bytes)."""
    try:
        with zipfile.ZipFile(_io(data)) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        return draft_from_entries(entries, drawing_part, rid)
    except Exception:
        return None


def _io(data: bytes):
    import io
    return io.BytesIO(data)
