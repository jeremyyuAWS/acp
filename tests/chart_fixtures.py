"""Builders for charts whose values live somewhere other than the chart part's caches.

A docx/pptx chart stores CACHES of its numbers next to a `<c:f>` cell range, with the authoritative
copy in an xlsx zipped inside the package (`word/embeddings/…`, `ppt/embeddings/…`). Word and
PowerPoint populate the caches; other generators leave them empty, and then the embedded workbook is
the only surviving copy. These builders produce that second shape, which no real fixture in the
repo has.

Shared rather than duplicated: both test_chart_data.py (parsing + descr injection) and
test_chart_datasheet.py (proposals) need the same package. Import as `from chart_fixtures import
…` — tests/ is not a package, and pytest's default prepend import mode puts this directory on
sys.path (same arrangement as engines.py).
"""
from __future__ import annotations

import io
import re
import zipfile

CHART_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <c:chart><c:title><c:tx><c:rich><a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
    ><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title>
  <c:plotArea><c:barChart><c:ser>
    <c:tx><c:strRef><c:f>Sheet!$B$1</c:f><c:strCache/></c:strRef></c:tx>
    <c:cat><c:strRef><c:f>Sheet!$A$2:$A$5</c:f><c:strCache/></c:strRef></c:cat>
    <c:val><c:numRef><c:f>Sheet!$B$2:$B$5</c:f><c:numCache/></c:numRef></c:val>
  </c:ser></c:barChart></c:plotArea></c:chart>
</c:chartSpace>"""

CHART_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package"
    Target="../embeddings/data.xlsx"/>
</Relationships>"""

DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body><w:p><w:r><w:drawing><wp:inline>
    <wp:docPr id="1" name="Chart 1"/>
    <a:graphic><a:graphicData><c:chart r:id="rId5"/></a:graphicData></a:graphic>
  </wp:inline></w:drawing></w:r></w:p></w:body>
</w:document>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"
    Target="charts/chart1.xml"/>
</Relationships>"""


def embedded_workbook(cats, vals) -> bytes:
    """The chart's data workbook, built by openpyxl — so its category labels are INLINE strings
    (`t="inlineStr"`), not shared strings. That is deliberate: on a docx/pptx the inlineStr branch
    in _read_cells is reachable ONLY through this embedded workbook."""
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active                 # openpyxl's default sheet name is "Sheet"
    ws.append(["Region", "Revenue"])
    for c, v in zip(cats, vals):
        ws.append([c, v])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def docx_chart_entries(cats, vals, title="Sales by region") -> dict:
    """A minimal but structurally honest docx: one cache-less chart, wired by relationship to
    word/embeddings/data.xlsx. Returns {part name: bytes}."""
    return {
        "word/document.xml": DOC_XML.encode(),
        "word/_rels/document.xml.rels": DOC_RELS.encode(),
        "word/charts/chart1.xml": CHART_XML.format(title=title).encode(),
        "word/charts/_rels/chart1.xml.rels": CHART_RELS.encode(),
        "word/embeddings/data.xlsx": embedded_workbook(cats, vals),
    }


def strip_caches(chart_xml: bytes) -> bytes:
    """Drop every <c:numCache>/<c:strCache> but keep the <c:f> ranges — i.e. turn a
    PowerPoint-authored chart into the cache-less kind, without touching anything else."""
    out = re.sub(rb"<c:(num|str)Cache>.*?</c:(num|str)Cache>", b"", chart_xml, flags=re.S)
    assert b"<c:f>" in out and b"Cache>" not in out, "fixture must keep refs and lose caches"
    return out


def rezip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in entries.items():
            z.writestr(n, b)
    return buf.getvalue()
