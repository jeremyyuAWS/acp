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
    assert render.render_page_png(b"whatever", ".docx", 1) is None      # office not renderable (phase 1)
    assert render.render_page_png(b"", ".pdf", 1) is None               # no bytes
    assert render.can_render(".pdf") and not render.can_render(".pptx")


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
