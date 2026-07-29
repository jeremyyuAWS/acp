"""Accurate alt text for NATIVE Office charts, read from the chart's own embedded data — no vision,
no confabulation (the honest answer to llava's chart-value problem, ADR 0016 / #123 follow-on).

A native PowerPoint/Word/Excel chart stores its real series, categories, and values in an OOXML
chart part (`ppt/charts/chartN.xml`, `word/charts/…`, `xl/charts/…`). So for these we don't need a
model to *guess* the numbers — we read them and state them exactly: "Bar chart 'Q4 Revenue by
Region': East highest at 150, West lowest at 50." Only FLATTENED chart images (a pasted PNG) still
need vision; a native chart is deterministic and correct.

Pure stdlib (zipfile + ElementTree), bytes in / list-of-alt-strings out, never raises — a chart it
can't parse is simply skipped (the vision path still covers it)."""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"

_CHART_PART = re.compile(r"^(?:ppt|word|xl)/charts/chart\d+\.xml$")
_TYPE_NAME = {
    "barChart": "Bar chart", "bar3DChart": "Bar chart", "lineChart": "Line chart",
    "line3DChart": "Line chart", "pieChart": "Pie chart", "pie3DChart": "Pie chart",
    "doughnutChart": "Doughnut chart", "areaChart": "Area chart", "scatterChart": "Scatter chart",
    "radarChart": "Radar chart", "stockChart": "Stock chart", "bubbleChart": "Bubble chart",
    "surfaceChart": "Surface chart", "ofPieChart": "Pie chart",
}
_OFFICE_EXTS = (".pptx", ".docx", ".xlsx")


def chart_alts(data: bytes, ext: str) -> list[str]:
    """Accurate alt-text strings for every native chart in an Office file (may be empty)."""
    return [describe_chart(c) for c in charts_in(data, ext)]


def charts_in(data: bytes, ext: str) -> list[dict]:
    """Parse every native chart part → [{type, title, series:[{name, points:[(cat,val)]}]}]."""
    if (ext or "").lower() not in _OFFICE_EXTS or not data:
        return []
    out: list[dict] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = {n: z.read(n) for n in z.namelist()}   # all parts, so cell refs can resolve
        for name in entries:
            if _CHART_PART.match(name):
                try:
                    c = _parse_chart(entries[name], entries)
                    if c and c.get("series"):
                        out.append(c)
                except Exception:
                    continue
    except Exception:
        return []
    return out


def _txt(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _cache_points(ref) -> list[str]:
    """Ordered <c:pt idx><c:v> values from a str/num cache, positioned by idx (gaps → '')."""
    if ref is None:
        return []
    pts = {}
    for pt in ref.iter(f"{{{_C}}}pt"):
        try:
            idx = int(pt.get("idx", "0"))
        except ValueError:
            idx = 0
        v = pt.find(f"{{{_C}}}v")
        pts[idx] = (v.text or "").strip() if v is not None else ""
    return [pts.get(i, "") for i in range(max(pts) + 1)] if pts else []


def _parse_chart(xml: bytes, entries: dict | None = None) -> dict | None:
    root = ET.fromstring(xml)
    chart = root.find(f"{{{_C}}}chart")
    if chart is None:
        return None
    title = _txt(chart.find(f"{{{_C}}}title"))
    plot = chart.find(f"{{{_C}}}plotArea")
    if plot is None:
        return None
    ctype, series = None, []
    for child in plot:
        tag = child.tag.split("}")[-1]
        if tag in _TYPE_NAME:
            ctype = ctype or _TYPE_NAME[tag]
            for ser in child.findall(f"{{{_C}}}ser"):
                name = _txt(ser.find(f"{{{_C}}}tx"))
                cats = _cache_points(ser.find(f"{{{_C}}}cat"))
                vals = _cache_points(ser.find(f"{{{_C}}}val"))
                # Real xlsx charts leave <c:numCache/> empty — the values are in cells. Resolve the
                # <c:f> range against the workbook so the alt states the ACTUAL numbers, not nothing.
                if entries is not None and not any(v != "" for v in vals):
                    vals = _resolve_ref(_ref_formula(ser.find(f"{{{_C}}}val")), entries) or vals
                if entries is not None and not any(c for c in cats):
                    cats = _resolve_ref(_ref_formula(ser.find(f"{{{_C}}}cat")), entries) or cats
                pts = [(cats[i] if i < len(cats) and cats[i] else f"item {i + 1}", vals[i])
                       for i in range(len(vals)) if vals[i] != ""]
                if pts:
                    series.append({"name": name, "points": pts})
    if not ctype or not series:
        return None
    return {"type": ctype, "title": title, "series": series}


def parse_chart_part(xml: bytes, entries: dict | None = None) -> dict | None:
    """Public single-part parser: one chart part's bytes → {type, title, series:[{name,
    points:[(cat, val)]}]}, or None when it carries nothing plottable. Pass `entries` (the whole
    package, part name → bytes) so an xlsx chart that stores only cell REFERENCES can resolve its
    real values. Namespace-correct (ElementTree), so it reads both the `c:`-prefixed chartSpace
    Excel/PowerPoint write and the default-namespace one openpyxl-family generators write. Never
    raises — an unparseable part is simply None."""
    try:
        return _parse_chart(xml, entries)
    except Exception:
        return None


def _ref_formula(el) -> str:
    """The <c:f> cell-range formula inside a <c:cat>/<c:val>, e.g. "'Sheet'!$B$6:$B$9", or ''."""
    if el is None:
        return ""
    f = el.find(f".//{{{_C}}}f")
    return (f.text or "").strip() if f is not None else ""


def _col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n


def _expand_range(rng: str) -> list[str]:
    """'B6:B9' → ['B6','B7','B8','B9']; a single cell → [cell]. Only straight-line ranges."""
    rng = rng.replace("$", "")
    if ":" not in rng:
        return [rng] if re.match(r"^[A-Za-z]+\d+$", rng) else []
    a, b = rng.split(":", 1)
    ma, mb = re.match(r"([A-Za-z]+)(\d+)", a), re.match(r"([A-Za-z]+)(\d+)", b)
    if not ma or not mb:
        return []
    c1, r1 = _col_to_num(ma.group(1)), int(ma.group(2))
    c2, r2 = _col_to_num(mb.group(1)), int(mb.group(2))
    out = []
    for c in range(min(c1, c2), max(c1, c2) + 1):
        col = ""
        cc = c
        while cc:
            cc, rem = divmod(cc - 1, 26)
            col = chr(65 + rem) + col
        for r in range(min(r1, r2), max(r1, r2) + 1):
            out.append(f"{col}{r}")
    return out[:64]                                         # bound — an alt needs a handful, not a sheet


def _resolve_ref(formula: str, entries: dict) -> list[str]:
    """Resolve "'Sheet Name'!$B$6:$B$9" to the cell values (numbers or shared-string text), in order."""
    m = re.match(r"^'?([^'!]+)'?!(.+)$", formula or "")
    if not m:
        return []
    sheet_name, rng = m.group(1), m.group(2)
    part = _xlsx_sheet_part(entries, sheet_name)
    if not part or part not in entries:
        return []
    cells = _expand_range(rng)
    if not cells:
        return []
    try:
        return _read_cells(entries[part], cells, _shared_strings(entries))
    except Exception:
        return []


def _xlsx_sheet_part(entries: dict, sheet_name: str) -> str | None:
    wb, rels = entries.get("xl/workbook.xml"), entries.get("xl/_rels/workbook.xml.rels")
    if not wb or not rels:
        return None
    _R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    _RE = "http://schemas.openxmlformats.org/package/2006/relationships"
    try:
        wbr = ET.fromstring(wb)
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        rid = None
        for s in wbr.iter(f"{ns}sheet"):
            if s.get("name") == sheet_name:
                rid = s.get(f"{{{_R}}}id")
                break
        if not rid:
            return None
        rr = ET.fromstring(rels)
        for rel in rr.findall(f"{{{_RE}}}Relationship"):
            if rel.get("Id") == rid:
                tgt = rel.get("Target", "").split("/")[-1]
                return f"xl/worksheets/{tgt}"
    except Exception:
        return None
    return None


def _shared_strings(entries: dict) -> list[str]:
    raw = entries.get("xl/sharedStrings.xml")
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
        return [_txt(si) for si in root]
    except Exception:
        return []


def _read_cells(sheet_xml: bytes, cells: list[str], shared: list[str]) -> list[str]:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    want = set(cells)
    found = {}
    root = ET.fromstring(sheet_xml)
    for c in root.iter(f"{ns}c"):
        ref = c.get("r")
        if ref not in want:
            continue
        v = c.find(f"{ns}v")
        val = (v.text or "") if v is not None else ""
        if c.get("t") == "inlineStr":                      # text lives in <is><t>, not <v>
            val = _txt(c.find(f"{ns}is"))                  # (openpyxl writes these; Excel shares)
        elif c.get("t") == "s":                            # shared-string index
            try:
                val = shared[int(val)]
            except (ValueError, IndexError):
                val = ""
        found[ref] = val
    return [found.get(ref, "") for ref in cells]


def _fmt_num(v: str) -> str:
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:g}"
    except (TypeError, ValueError):
        return str(v)


def describe_chart(chart: dict) -> str:
    """A concise, ACCURATE alt sentence from the chart's real data — the exact values, because they
    were read from the file, not guessed. Multi-series charts state the series; single-series charts
    state the high/low. Bounded so it stays alt-text, not a data dump."""
    ctype = chart.get("type", "Chart")
    title = chart.get("title", "")
    lead = f"{ctype} titled '{title}'" if title else ctype
    series = chart.get("series", [])
    if len(series) == 1:
        pts = series[0]["points"]
        nums = [(c, _to_float(v)) for c, v in pts if _to_float(v) is not None]
        cats = ", ".join(f"{c}" for c, _ in pts[:8])
        tail = f" spanning {len(pts)} categories" if len(pts) > 8 else ""
        if len(nums) >= 2:
            hi = max(nums, key=lambda x: x[1]); lo = min(nums, key=lambda x: x[1])
            return (f"{lead}: {cats}{tail}. Highest is {hi[0]} at {_fmt_num(str(hi[1]))}, "
                    f"lowest is {lo[0]} at {_fmt_num(str(lo[1]))}.")[:300]
        return f"{lead} comparing {cats}{tail}."[:300]
    names = ", ".join(s["name"] or f"series {i + 1}" for i, s in enumerate(series[:5]))
    cats = ", ".join(c for c, _ in series[0]["points"][:8])
    return f"{lead} comparing {names} across {cats}."[:300]


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Remediation: write accurate alt (descr) onto native chart shapes (1.1.1) ──────────────────────
# A native chart has NO image bytes, so the vision path can't help it — but its data is in the chart
# part, so we can write a correct, exact description with zero model risk. This adds descr= to a
# chart graphicFrame's <p:cNvPr> only when it lacks a real one (never overwrites a human's alt).
import posixpath

_CHART_RID = re.compile(r'<c:chart\b[^>]*r:id="(rId\d+)"')
_HAS_DESCR = re.compile(r'\bdescr="[^"]*\S[^"]*"')

# Per-format: which parts carry a drawing, which element wraps a chart, and which element carries the
# alt (descr). pptx → <p:graphicFrame>/<p:cNvPr>; xlsx → <xdr:graphicFrame>/<xdr:cNvPr>; docx → the
# inline/anchor drawing wrapper with alt on <wp:docPr>.
#
# The tag entries are regex fragments, so xlsx can carry an optional `xdr:` prefix: spreadsheet
# drawings come in two namespace flavours — Excel authors the prefixed `<xdr:graphicFrame>/
# <xdr:cNvPr>`, while openpyxl-family generators (and some export paths) emit the SAME parts in the
# DEFAULT spreadsheetDrawing namespace as `<graphicFrame>/<cNvPr>`. Matching only the prefixed form
# silently skipped every native chart in a default-namespace workbook: chart_descr_edits returned {}
# and the chart got no deterministic 1.1.1 alt at all. (Same bug class as `_ALT_TARGETS` in
# remediate_office.py, fixed the same way. docx/pptx are single-flavour, left as-is.)
_CHART_CFG = {
    ".pptx": (re.compile(r"^ppt/slides/slide\d+\.xml$"), [r"p:graphicFrame"], r"p:cNvPr"),
    ".xlsx": (re.compile(r"^xl/drawings/drawing\d+\.xml$"), [r"(?:xdr:)?graphicFrame"],
              r"(?:xdr:)?cNvPr"),
    ".docx": (re.compile(r"^word/document\.xml$"), [r"wp:inline", r"wp:anchor"], r"wp:docPr"),
}


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _rel_targets(entries: dict, part_name: str) -> dict:
    """{rId: resolved chart part path} from a part's .rels, resolving a relative Target (e.g.
    '../charts/chart1.xml') against the part's own directory — so it works for slides, drawings, and
    the docx body alike, not just 'ppt/charts/'."""
    d, base = part_name.rsplit("/", 1) if "/" in part_name else ("", part_name)
    rels_name = f"{d}/_rels/{base}.rels" if d else f"_rels/{base}.rels"
    raw = entries.get(rels_name)
    if not raw:
        return {}
    _RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
    out = {}
    try:
        root = ET.fromstring(raw)
    except Exception:
        return {}
    for rel in root.findall(f"{{{_RELS}}}Relationship"):
        rid, tgt = rel.get("Id"), rel.get("Target") or ""
        if rid and "chart" in tgt:
            out[rid] = posixpath.normpath(posixpath.join(d, tgt)) if not tgt.startswith("/") else tgt.lstrip("/")
    return out


def chart_descr_edits(entries: dict, ext: str) -> dict:
    """{part_name: (new_xml_bytes, [alts])} for every native chart (pptx/xlsx/docx) that lacked alt and
    got an accurate descr from its own data. Pure, format-aware string surgery: it only inserts a
    descr attribute on the chart's alt-carrying element, never touches anything else, never overwrites
    a real descr, and leaves a part it can't handle unchanged."""
    cfg = _CHART_CFG.get((ext or "").lower())
    if not cfg:
        return {}
    part_re, block_tags, descr_tag = cfg
    # Group 1 captures the tag name AS WRITTEN in this file (`cNvPr` or `xdr:cNvPr`) — the
    # replacement below must re-emit that exact name, never the pattern it was matched with.
    descr_re = re.compile(rf"<({descr_tag})\b([^>]*?)(/?)>")
    changed: dict = {}
    for name in list(entries):
        if not part_re.match(name):
            continue
        try:
            xml = entries[name].decode("utf-8")
        except Exception:
            continue
        rels = _rel_targets(entries, name)
        if not rels:
            continue
        alts, new_xml, moved = [], xml, False
        for btag in block_tags:
            # \1 backreference: a block must close with the SAME spelling it opened with, so an
            # unprefixed <graphicFrame> can never be paired with an </xdr:graphicFrame>.
            for bm in re.finditer(rf"<({btag})\b.*?</\1>", new_xml, re.S):
                block = bm.group(0)
                rid_m = _CHART_RID.search(block)
                if not rid_m:
                    continue
                chart_part = rels.get(rid_m.group(1))
                if not chart_part or chart_part not in entries:
                    continue
                try:
                    chart = _parse_chart(entries[chart_part], entries)
                except Exception:
                    chart = None
                if not chart:
                    continue
                alt = describe_chart(chart)
                dm = descr_re.search(block)
                if not dm or _HAS_DESCR.search(dm.group(2)):
                    continue                               # no target element, or already has a real descr
                new_block = (block[:dm.start()]
                             + f"<{dm.group(1)}{dm.group(2)} descr=\"{_xml_escape(alt)}\"{dm.group(3)}>"
                             + block[dm.end():])
                new_xml = new_xml.replace(block, new_block, 1)
                alts.append(alt); moved = True
        if moved:
            changed[name] = (new_xml.encode("utf-8"), alts)
    return changed


def slide_chart_descr(entries: dict) -> dict:
    """Back-compat alias for the pptx path (kept for existing callers)."""
    return chart_descr_edits(entries, ".pptx")
