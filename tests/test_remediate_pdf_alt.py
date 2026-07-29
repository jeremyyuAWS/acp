"""Tests for vision-generated PDF figure alt text (WCAG 1.1.1).

remediate_pdf sets /Alt on tagged /Figure struct elements that lack it, from a local
vision-model description of the figure's page — exactly what the pdf.missing-alt-text
analyser reads. The vision model is stubbed so these run offline; the live end-to-end
(real llava → /Alt written → analyser re-scan clears 1.1.1) is exercised separately.
Self-skips when pikepdf / pypdf / reportlab, or the partner PDF engine, are unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pypdf")
pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai  # noqa: E402
import remediate_pdf as RP  # noqa: E402

# remediate_pdf() imports the partner PDF engine, a separate repo located via scanner.WP /
# $ACP_PDF_ENGINE and absent on a clean CI agent. Skip there rather than hard-fail.
from conftest import requires_pdf_engine  # noqa: E402

pytestmark = requires_pdf_engine


def _tagged_pdf_with_figure(path: Path, *, tagged: bool = True, with_alt: bool = False) -> None:
    """A 1-page PDF; when tagged, its struct tree has one /Figure (optionally with /Alt)."""
    raw = path.with_name("raw-" + path.name)
    c = canvas.Canvas(str(raw))
    c.drawString(72, 720, "Figure below")
    c.rect(120, 480, 200, 150, fill=1)     # a filled box stands in for the image
    c.showPage()
    c.save()
    pdf = pikepdf.open(str(raw))
    if tagged:
        page = pdf.pages[0].obj
        fig = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"),
                                 S=pikepdf.Name("/Figure"), Pg=page, K=0)
        if with_alt:
            fig.Alt = pikepdf.String("Author supplied description")
        doc = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/Document"))
        fig_ref = pdf.make_indirect(fig)
        doc_ref = pdf.make_indirect(doc)
        doc.K = pikepdf.Array([fig_ref])
        fig.P = doc_ref
        st = pikepdf.Dictionary(Type=pikepdf.Name("/StructTreeRoot"), K=pikepdf.Array([doc_ref]))
        st_ref = pdf.make_indirect(st)
        doc.P = st_ref
        pdf.Root.StructTreeRoot = st_ref
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    pdf.save(str(path))
    pdf.close()


def _figure_alts(pdf_path: Path) -> list[str]:
    pdf = pikepdf.open(str(pdf_path))
    alts: list[str] = []

    def walk(n):
        if isinstance(n, pikepdf.Dictionary):
            if str(n.get("/S", "")) == "/Figure":
                alts.append(str(n.get("/Alt", "")))
            for k in ("/K", "/C"):
                if k in n:
                    c = n[k]
                    for it in (c if isinstance(c, pikepdf.Array) else [c]):
                        walk(it)
        elif isinstance(n, pikepdf.Array):
            for it in n:
                walk(it)

    if "/StructTreeRoot" in pdf.Root:
        walk(pdf.Root["/StructTreeRoot"])
    pdf.close()
    return alts


def _stub_vision(monkeypatch, alt="A filled box representing the quarterly figure", available=True,
                 grounded=True):
    calls = {"n": 0}

    def fake(image_bytes, **kw):
        calls["n"] += 1
        # `grounded` drives the honesty split, as it does for office: a description anchored in
        # text read from the page render is written inline; an ungrounded guess is withheld and
        # deferred to a review card. (It is a weaker anchor here — the render is the whole PAGE,
        # so it says the page carried text, not the figure. Weaker is not nothing.)
        return {"alt": alt, "grounded": grounded, "evidence": "stub", "model": "llava:7b"} if alt else None

    monkeypatch.setattr(ai, "vision_is_available", lambda: available)
    monkeypatch.setattr(ai, "describe_image_structured", fake)
    return calls


def test_pdf_figure_alt_set_by_vision(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "fig.pdf"
    _tagged_pdf_with_figure(src)
    fixed, applied, skipped = RP.remediate_pdf(src, ai_enabled=True)
    assert fixed is not None
    assert _figure_alts(Path(fixed)) == ["A filled box representing the quarterly figure"]
    assert any("Alt text" in a and "1.1.1" in a for a in applied)
    assert not any("figure(s) need human alt text" in s for s in skipped)
    assert calls["n"] == 1


def test_pdf_existing_figure_alt_untouched(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "hasalt.pdf"
    _tagged_pdf_with_figure(src, with_alt=True)
    fixed, applied, _ = RP.remediate_pdf(src, ai_enabled=True)
    assert _figure_alts(Path(fixed or src)) == ["Author supplied description"]
    assert calls["n"] == 0                       # vision never called for a figure that has alt


def test_pdf_alt_deferred_when_ai_off(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "off.pdf"
    _tagged_pdf_with_figure(src)
    fixed, applied, skipped = RP.remediate_pdf(src, ai_enabled=False)
    assert calls["n"] == 0
    assert _figure_alts(Path(fixed or src)) == [""]        # no /Alt written
    assert any("figure(s) need human alt text" in s for s in skipped)


def test_pdf_alt_deferred_when_vision_unavailable(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch, available=False)
    src = tmp_path / "novis.pdf"
    _tagged_pdf_with_figure(src)
    fixed, applied, skipped = RP.remediate_pdf(src, ai_enabled=True)
    assert calls["n"] == 0
    assert any("figure(s) need human alt text" in s for s in skipped)


def test_pdf_alt_deferred_on_vision_miss(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch, alt=None)          # model returns nothing usable
    src = tmp_path / "miss.pdf"
    _tagged_pdf_with_figure(src)
    fixed, applied, skipped = RP.remediate_pdf(src, ai_enabled=True)
    assert calls["n"] == 1
    assert _figure_alts(Path(fixed or src)) == [""]
    assert any("figure(s) need human alt text" in s for s in skipped)


def test_pdf_ungrounded_alt_deferred_end_to_end(tmp_path, monkeypatch):
    # Whole-document path: an ungrounded description leaves the file unlabelled and the 1.1.1
    # finding open, rather than shipping a guess as the figure's accessible name.
    calls = _stub_vision(monkeypatch, alt="A person near a building", grounded=False)
    src = tmp_path / "unground.pdf"
    _tagged_pdf_with_figure(src)
    fixed, applied, skipped = RP.remediate_pdf(src, ai_enabled=True)
    assert calls["n"] == 1                                 # the model ran…
    assert _figure_alts(Path(fixed or src)) == [""]        # …and its guess was not written
    assert not any("Alt text" in a for a in applied)
    assert any("figure(s) need human alt text" in s for s in skipped)


def test_pdf_untagged_no_alt_work(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "untagged.pdf"
    _tagged_pdf_with_figure(src, tagged=False)
    fixed, applied, skipped = RP.remediate_pdf(src, ai_enabled=True)
    assert calls["n"] == 0                               # no figures → no vision
    assert not any("need human alt text" in s for s in skipped)
