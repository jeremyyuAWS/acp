"""Arbitrary-page PDF rendering — the 'locate in document' evidence primitive (page clamp)."""
import importlib.util
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import render  # noqa: E402

_CORPUS = Path(__file__).resolve().parent.parent / "test-corpus/oracle"
_HAS_PDFIUM = importlib.util.find_spec("pypdfium2") is not None


def test_non_renderable_and_empty_return_none():
    assert render.render_page_png(b"", ".pdf", 1) is None               # no bytes → None always
    assert render.render_page_png(b"whatever", ".xyz", 1) is None       # unknown type → None always
    assert render.can_render(".pdf")
    # ADR 0018: Office is renderable ONLY where LibreOffice is on PATH; without it, it degrades
    # to "no preview" exactly like an unsupported type. So can_render(".pptx") tracks soffice.
    assert render.can_render(".pptx") is (render._soffice() is not None)
    assert not render.can_render(".txt")                                # never renderable
    # On the API tier (no LibreOffice), office bytes can't rasterize → None. Where soffice IS
    # present, LibreOffice may render a blank page for junk bytes — a harmless empty preview,
    # not a failure mode, so we only assert the no-soffice contract here.
    if render._soffice() is None:
        assert render.render_page_png(b"whatever", ".docx", 1) is None


@pytest.mark.skipif(not _HAS_PDFIUM, reason="pypdfium2 not installed in this env")
def test_render_page_clamps_and_back_compat():
    data = (_CORPUS / "pdf-titled-lang.pdf").read_bytes()
    p1 = render.render_page_png(data, ".pdf", 1)
    assert p1 and p1.startswith(b"\x89PNG")                             # real PNG for page 1
    # An out-of-range page is CLAMPED to the last page, never None (locate must always show something).
    far = render.render_page_png(data, ".pdf", 9999)
    assert far and far.startswith(b"\x89PNG")
    # Page 0 / negative also clamp to page 1.
    assert render.render_page_png(data, ".pdf", 0) == p1
    # Back-compat: the ADR-0015 thumbnail wrapper still renders page 1 identically.
    assert render.render_page1_png(data, ".pdf") == p1
