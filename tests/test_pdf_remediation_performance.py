"""Performance regressions for the production PDF remediation path.

These are call-count benchmarks, not wall-clock thresholds: CI speed varies, while each
duplicate page call costs one OCR pass plus a 30-90 second CPU vision wait in production.
The fixture deliberately puts several /Figure elements on the same page because the PDF
remediator captions a whole-page render, making their expensive inputs byte-identical.
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
def test_same_page_figures_share_one_ocr_and_vision_result(tmp_path, monkeypatch, result):
    """A successful description and a miss are both reusable page-level results."""
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

    with pikepdf.open(str(src)) as pdf:
        applied, deferred = rp._fix_pdf_figure_alt(
            pdf, str(src), ai_enabled=True, scan_id=None, file=src.name,
            proposals=[], applied_fixes=[])

    assert calls == {"render": 1, "ocr_and_vision": 1}
    assert (len(applied), deferred) == ((3, 0) if result else (0, 3))


def test_different_pages_do_not_share_vision_evidence(tmp_path, monkeypatch):
    """The cache boundary is the page: evidence must never leak across page renders."""
    src = tmp_path / "two-pages.pdf"
    _tagged_pdf(src, n_figs=2)
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf:
        pdf.add_blank_page(page_size=(612, 792))
        figures = rp._collect_figures(pdf.Root["/StructTreeRoot"])
        figures[1]["/Pg"] = pdf.pages[1].obj
        pdf.save(str(src))

    seen = []
    monkeypatch.setattr(rp, "_render_page_png", lambda _p, page: bytes([page]) + _png())
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)

    def describe(image, **_kwargs):
        seen.append(image[0])
        return {"alt": f"Description for page {image[0]}", "grounded": True,
                "evidence": "stub", "model": "stub-vision"}

    monkeypatch.setattr(ai, "describe_image_structured", describe)
    with pikepdf.open(str(src)) as pdf:
        applied, deferred = rp._fix_pdf_figure_alt(
            pdf, str(src), ai_enabled=True, scan_id=None, file=src.name)

    assert seen == [1, 2]
    assert len(applied) == 2 and deferred == 0
