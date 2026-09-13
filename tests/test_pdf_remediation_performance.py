"""Manual PDF figure context renders each page once and never dispatches page vision.

A page image is useful browsing context, but it cannot provide an automatic caption
for an unmapped Figure. These real tagged-PDF fixtures preserve render caching and
page isolation while pinning zero OCR/vision work and zero written/applied alt text.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("reportlab")
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai  # noqa: E402
import remediate_pdf as rp  # noqa: E402
from test_pdf_figure_alt_approval import _tagged_pdf  # noqa: E402


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(out, format="PNG")
    return out.getvalue()


@pytest.mark.parametrize("result", [
    {"alt": "Quarterly revenue chart", "grounded": True,
     "evidence": "stub", "model": "stub-vision"},
    None,
])
def test_same_page_manual_figures_share_context_render_without_vision(tmp_path, monkeypatch, result):
    """Even an available grounded model must not caption whole-page context."""
    src = tmp_path / "three-figures-one-page.pdf"
    _tagged_pdf(src, n_figs=3)
    calls = {"render": 0, "ocr_and_vision": 0}

    def render(*_args, **_kwargs):
        calls["render"] += 1
        return _png()

    def describe(*_args, **_kwargs):
        calls["ocr_and_vision"] += 1
        return result

    monkeypatch.setattr(rp, "_render_page_png", render)
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_image_structured", describe)

    props, fixes = [], []
    with pikepdf.open(str(src)) as pdf:
        applied, deferred = rp._fix_pdf_figure_alt(
            pdf, str(src), ai_enabled=True, scan_id=None, file=src.name,
            proposals=props, applied_fixes=fixes)
        assert all(rp._fig_alt(f) is None for f in rp._collect_figures(pdf.Root.StructTreeRoot))

    assert calls == {"render": 1, "ocr_and_vision": 0}
    assert applied == [] and fixes == [] and deferred == 3
    assert [p["locator"] for p in props] == ["pdf:fig:1:0", "pdf:fig:1:1", "pdf:fig:1:2"]
    assert len({p["thumb"] for p in props}) == 1
    assert all(not p["proposed_value"] for p in props)


def test_different_pages_keep_distinct_manual_context_thumbnails(tmp_path, monkeypatch):
    """Page thumbnails cannot be reused for a figure belonging to another page."""
    src = tmp_path / "two-pages.pdf"
    _tagged_pdf(src, n_figs=2)
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf:
        pdf.add_blank_page(page_size=(612, 792))
        figures = rp._collect_figures(pdf.Root["/StructTreeRoot"])
        figures[1]["/Pg"] = pdf.pages[1].obj
        pdf.save(str(src))

    import base64
    rendered, described = [], []

    def render(_path, page):
        rendered.append(page)
        out = io.BytesIO()
        Image.new("RGB", (600, 800), (page, 0, 0)).save(out, format="PNG")
        return out.getvalue()

    def describe(image, **kwargs):
        described.append(image)
        return {"alt": "Unrelated page caption", "grounded": True, "model": "stub"}

    monkeypatch.setattr(rp, "_render_page_png", render)
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_image_structured", describe)
    props, fixes = [], []
    with pikepdf.open(str(src)) as pdf:
        applied, deferred = rp._fix_pdf_figure_alt(
            pdf, str(src), ai_enabled=True, scan_id=None, file=src.name,
            proposals=props, applied_fixes=fixes)
        assert all(rp._fig_alt(f) is None for f in rp._collect_figures(pdf.Root.StructTreeRoot))

    assert rendered == [1, 2] and described == []
    assert applied == [] and fixes == [] and deferred == 2
    assert [p["locator"] for p in props] == ["pdf:fig:1:0", "pdf:fig:2:0"]
    pixels = [Image.open(io.BytesIO(base64.b64decode(p["thumb"].split(",", 1)[1]))).getpixel((0, 0))
              for p in props]
    assert pixels == [(1, 0, 0), (2, 0, 0)]
    assert all(not p["proposed_value"] for p in props)
