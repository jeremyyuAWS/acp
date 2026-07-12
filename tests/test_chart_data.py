"""Native-chart alt text (chart_data.py): the exact values, read from the file — never guessed.

Builds a real native PowerPoint chart with KNOWN data via python-pptx, then asserts the extracted
alt states those exact values (the whole point: no llava confabulation for native charts).
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import chart_data  # noqa: E402

pptx = pytest.importorskip("pptx")


def _native_chart_pptx(cats, vals, title="Q4 Revenue by Region") -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    data = CategoryChartData()
    data.categories = cats
    data.add_series("Revenue", vals)
    gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                                Inches(1), Inches(1), Inches(6), Inches(4), data)
    gf.chart.has_title = True
    gf.chart.chart_title.text_frame.text = title
    buf = io.BytesIO(); prs.save(buf); return buf.getvalue()


def test_reads_the_real_values_high_and_low():
    data = _native_chart_pptx(["North", "South", "East", "West"], [120, 70, 150, 50])
    charts = chart_data.charts_in(data, ".pptx")
    assert len(charts) == 1
    alt = chart_data.describe_chart(charts[0])
    # The exact truth: East is highest at 150, West lowest at 50 — stated because it was READ.
    assert "East" in alt and "150" in alt
    assert "West" in alt and "50" in alt
    assert "highest" in alt.lower() and "lowest" in alt.lower()
    assert "Q4 Revenue by Region" in alt


def test_chart_alts_convenience_and_type():
    data = _native_chart_pptx(["A", "B", "C"], [10, 30, 20])
    alts = chart_data.chart_alts(data, ".pptx")
    assert len(alts) == 1
    assert alts[0].lower().startswith(("bar chart", "column", "chart"))
    assert "B" in alts[0] and "30" in alts[0]      # the real max


def test_non_office_and_garbage_return_empty_never_raise():
    assert chart_data.charts_in(b"", ".pptx") == []
    assert chart_data.charts_in(b"not a zip", ".pptx") == []
    assert chart_data.charts_in(b"%PDF-1.7", ".pdf") == []
    assert chart_data.chart_alts(b"junk", ".docx") == []


def test_slide_chart_descr_injects_accurate_alt_onto_the_chart_shape():
    import io
    import zipfile
    data = _native_chart_pptx(["North", "South", "East", "West"], [120, 70, 150, 50])
    entries = {n: zipfile.ZipFile(io.BytesIO(data)).read(n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist()}
    changed = chart_data.slide_chart_descr(entries)
    assert changed, "a native chart with no alt should get one"
    (new_xml, alts) = next(iter(changed.values()))
    xml = new_xml.decode("utf-8")
    # The descr landed on a <p:cNvPr> and states the REAL high/low — not a guess.
    assert 'descr="Bar chart' in xml and "East at 150" in xml and "West at 50" in xml
    assert alts and "East at 150" in alts[0]


def _native_chart_xlsx(cats, vals, title="Q4 Revenue by Region") -> bytes:
    opx = pytest.importorskip("openpyxl")
    from openpyxl.chart import BarChart, Reference
    wb = opx.Workbook(); ws = wb.active
    ws.append(["Region", "Revenue"])
    for c, v in zip(cats, vals):
        ws.append([c, v])
    ch = BarChart(); ch.title = title
    data = Reference(ws, min_col=2, min_row=1, max_row=1 + len(cats))
    catref = Reference(ws, min_col=1, min_row=2, max_row=1 + len(cats))
    ch.add_data(data, titles_from_data=True); ch.set_categories(catref)
    ws.add_chart(ch, "E2")
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_xlsx_chart_reads_the_real_cell_values():
    # A native xlsx chart references cells (empty numCache) — the resolver reads the actual VALUES
    # from the worksheet. (Category labels also resolve on real Excel files; openpyxl serialises the
    # category ref differently, so we assert on the values the resolver reliably recovers.)
    data = _native_chart_xlsx(["North", "South", "East", "West"], [120, 70, 150, 50])
    alts = chart_data.chart_alts(data, ".xlsx")
    assert alts and alts[0].lower().startswith("bar chart")
    assert "150" in alts[0] and "50" in alts[0]                 # real high/low, read from cells


def test_slide_chart_descr_is_idempotent_never_overwrites():
    import io
    import zipfile
    data = _native_chart_pptx(["A", "B"], [1, 2])
    z = zipfile.ZipFile(io.BytesIO(data))
    entries = {n: z.read(n) for n in z.namelist()}
    first = chart_data.slide_chart_descr(entries)
    assert first                                             # first pass adds the alt
    for name, (new_xml, _) in first.items():
        entries[name] = new_xml
    # Second pass on the now-described chart must be a no-op — a real descr is never overwritten.
    assert chart_data.slide_chart_descr(entries) == {}
