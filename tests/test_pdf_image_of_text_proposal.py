"""Tests for PDF 1.4.5/1.4.9 image-of-text proposal helpers in proposals.py.

Covers:
  _figure_objr_xobj   — finds (page, xobj_name) for a /Figure via its OBJR /K child
  _pdf_struct_image_map — builds {(page, name): locator} over the struct tree
  _propose_pdf_images_of_text — end-to-end: returns proposals only for OBJR-linked /Figures
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import proposals as _mod  # noqa: E402


# ── helpers to build minimal pikepdf-like objects ──────────────────────────────
# proposals.py uses pikepdf.Dictionary, pikepdf.Array, and objgen comparisons.
# We use real pikepdf here since it is installed in the test environment.

try:
    import pikepdf
    _PIKEPDF = True
except ImportError:
    _PIKEPDF = False

pytestmark = pytest.mark.skipif(not _PIKEPDF, reason="pikepdf not installed")


def _make_minimal_pdf_with_figure(*, with_objr: bool) -> bytes:
    """Build a tagged PDF containing one page with one image XObject.

    When `with_objr=True`, the /Figure struct element has an OBJR /K child pointing to
    the image XObject, so _figure_objr_xobj can resolve it.  When False, /K is an MCID
    integer — a Tier-2 case that _pdf_struct_image_map silently skips.
    """
    import pikepdf

    # Build a minimal 4×4 white image as an XObject
    img_bytes = _minimal_png_bytes()

    with pikepdf.Pdf.new() as pdf:
        page = pikepdf.Page(pikepdf.Dictionary(
            Type=pikepdf.Name("/Page"),
            MediaBox=pikepdf.Array([0, 0, 72, 72]),
            Resources=pikepdf.Dictionary(
                XObject=pikepdf.Dictionary()
            ),
        ))
        pdf.pages.append(page)
        page_obj = pdf.pages[0].obj

        # Add an image XObject
        img_xobj = pikepdf.Stream(pdf, img_bytes)
        img_xobj.stream_dict = pikepdf.Dictionary(
            Type=pikepdf.Name("/XObject"),
            Subtype=pikepdf.Name("/Image"),
            Width=4, Height=4,
            ColorSpace=pikepdf.Name("/DeviceRGB"),
            BitsPerComponent=8,
        )
        img_ref = pdf.make_indirect(img_xobj)
        page_obj.Resources.XObject["/Im0"] = img_ref

        # Build struct elements
        if with_objr:
            objr = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name("/OBJR"),
                Obj=img_ref,
                Pg=page_obj,
            ))
            fig_k = objr
        else:
            fig_k = pikepdf.Integer(0)   # MCID — Tier 2, not handled

        fig = pdf.make_indirect(pikepdf.Dictionary(
            S=pikepdf.Name("/Figure"),
            Pg=page_obj,
            K=fig_k,
        ))
        struct_root = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name("/StructTreeRoot"),
            K=fig,
        ))
        pdf.Root.StructTreeRoot = struct_root

        buf = io.BytesIO()
        pdf.save(buf)
        return buf.getvalue()


def _minimal_png_bytes() -> bytes:
    """4×4 white RGB PNG — small but valid enough for pikepdf PdfImage tests."""
    import struct, zlib
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xFFFFFFFF)

    # IHDR: 4×4, 8-bit, RGB
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    # raw scanlines (filter byte 0x00 + 4 pixels × 3 channels white)
    raw = (b"\x00" + b"\xff" * 12) * 4
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


# ── _figure_objr_xobj ──────────────────────────────────────────────────────────

class TestFigureObjrXobj:
    def test_returns_page_and_name_for_objr_figure(self):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=True)
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            struct_root = pdf.Root.StructTreeRoot
            from formats.pdf.structure import collect_figures
            figures = collect_figures(struct_root)
            assert len(figures) == 1
            fig = figures[0]
            page_map = {pdf.pages[0].objgen[0]: 1}
            page_num, xobj_name = _mod._figure_objr_xobj(fig, pdf, page_map)
        assert page_num == 1
        assert xobj_name == "/Im0"

    def test_returns_none_for_mcid_figure(self):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=False)
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            struct_root = pdf.Root.StructTreeRoot
            from formats.pdf.structure import collect_figures
            figures = collect_figures(struct_root)
            assert len(figures) == 1
            fig = figures[0]
            page_map = {pdf.pages[0].objgen[0]: 1}
            page_num, xobj_name = _mod._figure_objr_xobj(fig, pdf, page_map)
        assert page_num is None
        assert xobj_name is None


# ── _pdf_struct_image_map ──────────────────────────────────────────────────────

class TestPdfStructImageMap:
    def test_objr_figure_appears_in_map(self):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=True)
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            result = _mod._pdf_struct_image_map(pdf)
        assert (1, "/Im0") in result
        assert result[(1, "/Im0")] == "pdf:fig:1:0"

    def test_mcid_figure_absent_from_map(self):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=False)
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            result = _mod._pdf_struct_image_map(pdf)
        assert result == {}

    def test_untagged_pdf_returns_empty(self):
        with pikepdf.Pdf.new() as pdf:
            page = pikepdf.Page(pikepdf.Dictionary(
                Type=pikepdf.Name("/Page"),
                MediaBox=pikepdf.Array([0, 0, 72, 72]),
            ))
            pdf.pages.append(page)
            buf = io.BytesIO()
            pdf.save(buf)
            pdf_bytes = buf.getvalue()
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            result = _mod._pdf_struct_image_map(pdf)
        assert result == {}


# ── _propose_pdf_images_of_text ────────────────────────────────────────────────

class TestProposePdfImagesOfText:
    def test_emits_pdf_fig_locator_for_objr_figure(self, tmp_path):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=True)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(pdf_bytes)

        # Stub OCR so the test never calls tesseract
        with (
            patch("ocr.is_available", return_value=True),
            patch("ocr._ocr_words", return_value=5),
            patch("ocr.ocr_text", return_value="hello world text"),
            patch("ocr._MIN_WORDS", 3),
            patch("ocr._MIN_PIXELS", 100),
            patch("ocr._MIN_WORDS_STRICT", 1),
            patch("ocr._MIN_PIXELS_STRICT", 50),
        ):
            results = _mod._propose_pdf_images_of_text(pdf_path)

        assert len(results) == 1
        assert results[0]["locator"] == "pdf:fig:1:0"
        assert results[0]["proposed_value"] == "hello world text"

    def test_skips_mcid_only_figures(self, tmp_path):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=False)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(pdf_bytes)

        with (
            patch("ocr.is_available", return_value=True),
            patch("ocr._ocr_words", return_value=5),
            patch("ocr.ocr_text", return_value="hello world"),
            patch("ocr._MIN_WORDS", 3),
            patch("ocr._MIN_PIXELS", 100),
            patch("ocr._MIN_WORDS_STRICT", 1),
            patch("ocr._MIN_PIXELS_STRICT", 50),
        ):
            results = _mod._propose_pdf_images_of_text(pdf_path)

        assert results == []

    def test_returns_empty_when_ocr_unavailable(self, tmp_path):
        pdf_bytes = _make_minimal_pdf_with_figure(with_objr=True)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(pdf_bytes)

        with patch("ocr.is_available", return_value=False):
            results = _mod._propose_pdf_images_of_text(pdf_path)

        assert results == []


# ── propose_images_of_text (non-PDF still uses "image N") ─────────────────────

class TestProposeImagesOfTextPptx:
    def test_pptx_ext_uses_image_n_locator(self, tmp_path):
        with (
            patch("ocr.is_available", return_value=True),
            patch("ocr._embedded_images", return_value=[b"imgbytes"]),
            patch("ocr._ocr_words", return_value=5),
            patch("ocr.ocr_text", return_value="slide text"),
            patch("ocr._MIN_WORDS", 3),
            patch("ocr._MIN_PIXELS", 100),
            patch("ocr._MIN_WORDS_STRICT", 1),
            patch("ocr._MIN_PIXELS_STRICT", 50),
            patch.object(_mod, "thumb_b64", return_value=""),
        ):
            results = _mod.propose_images_of_text(tmp_path / "x.pptx", ".pptx")

        assert len(results) == 1
        assert results[0]["locator"] == "image 1"
