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
            for name in z.namelist():
                if _CHART_PART.match(name):
                    try:
                        c = _parse_chart(z.read(name))
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


def _parse_chart(xml: bytes) -> dict | None:
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
                pts = [(cats[i] if i < len(cats) else f"item {i + 1}", vals[i])
                       for i in range(len(vals)) if vals[i] != ""]
                if pts:
                    series.append({"name": name, "points": pts})
    if not ctype or not series:
        return None
    return {"type": ctype, "title": title, "series": series}


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
_GRAPHICFRAME = re.compile(r"<p:graphicFrame\b.*?</p:graphicFrame>", re.S)
_CHART_RID = re.compile(r'<c:chart\b[^>]*r:id="(rId\d+)"')
_CNVPR = re.compile(r"<p:cNvPr\b([^>]*?)(/?)>")
_HAS_DESCR = re.compile(r'\bdescr="[^"]*\S[^"]*"')
_SLIDE = re.compile(r"^ppt/slides/slide\d+\.xml$")


def _slide_rel_targets(entries: dict, slide_name: str) -> dict:
    """{rId: chart part name} from a slide's .rels — resolving '../charts/chartN.xml' to a full path."""
    rels_name = slide_name.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    raw = entries.get(rels_name)
    if not raw:
        return {}
    out = {}
    try:
        root = ET.fromstring(raw)
    except Exception:
        return {}
    _RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
    for rel in root.findall(f"{{{_RELS}}}Relationship"):
        rid, tgt = rel.get("Id"), rel.get("Target") or ""
        if rid and "chart" in tgt:
            out[rid] = "ppt/charts/" + tgt.split("/")[-1]
    return out


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def slide_chart_descr(entries: dict) -> dict:
    """{slide_part_name: (new_xml_bytes, [alts])} for slides where a native chart graphicFrame lacked
    alt and got an accurate descr from its own data. Pure string surgery on the slide XML — only
    inserts a descr attribute on a chart's <p:cNvPr>, never touches anything else, never overwrites an
    existing real descr. Best-effort: a slide it can't handle is simply left unchanged."""
    changed: dict = {}
    for name in list(entries):
        if not _SLIDE.match(name):
            continue
        try:
            xml = entries[name].decode("utf-8")
        except Exception:
            continue
        rels = _slide_rel_targets(entries, name)
        if not rels:
            continue
        alts, new_xml, moved = [], xml, False
        for gf in _GRAPHICFRAME.finditer(xml):
            block = gf.group(0)
            rid_m = _CHART_RID.search(block)
            if not rid_m:
                continue
            chart_part = rels.get(rid_m.group(1))
            if not chart_part or chart_part not in entries:
                continue
            try:
                chart = _parse_chart(entries[chart_part])
            except Exception:
                chart = None
            if not chart:
                continue
            alt = describe_chart(chart)
            cnv = _CNVPR.search(block)
            if not cnv or _HAS_DESCR.search(cnv.group(1)):
                continue                                   # no cNvPr, or already has a real descr
            new_cnv = f"<p:cNvPr{cnv.group(1)} descr=\"{_xml_escape(alt)}\"{cnv.group(2)}>"
            new_block = block[:cnv.start()] + new_cnv + block[cnv.end():]
            new_xml = new_xml.replace(block, new_block, 1)
            alts.append(alt); moved = True
        if moved:
            changed[name] = (new_xml.encode("utf-8"), alts)
    return changed
