"""Synthetic PDF/DOCX fixture builders. No binaries are committed — every fixture is
built at test time from these functions, using libraries already declared as project
dependencies (`pikepdf`, `pypdf`, `python-docx` in `api/requirements.txt` /
`tests/requirements.txt`).
"""
from __future__ import annotations

import struct
import zlib
from io import BytesIO

import docx
import pikepdf
import pypdf


def make_pdf(
    *,
    page_count: int = 1,
    field_names: tuple[str, ...] = ("Text1",),
    field_tu: tuple[str | None, ...] | None = None,
) -> bytes:
    """Build a minimal valid PDF with `page_count` blank pages and one AcroForm text
    field per name in `field_names`, all on page 1. `field_tu`, when given, sets each
    field's existing /TU (accessible name) — parallel to `field_names`, None entries
    leave that field unnamed. Mirrors exactly the AcroForm shape
    `api/remediate_pdf.py`'s `_collect_form_fields`/`apply_pdf_field_name` expect.
    """
    if field_tu is None:
        field_tu = (None,) * len(field_names)
    assert len(field_tu) == len(field_names)

    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    base = buf.getvalue()

    pdf = pikepdf.open(BytesIO(base))
    page = pdf.pages[0]
    field_refs = []
    for i, (name, tu) in enumerate(zip(field_names, field_tu)):
        kw = dict(
            FT=pikepdf.Name("/Tx"),
            T=pikepdf.String(name),
            Rect=pikepdf.Array([50, 700 - 30 * i, 250, 720 - 30 * i]),
            Subtype=pikepdf.Name("/Widget"),
            Type=pikepdf.Name("/Annot"),
            F=4,
        )
        if tu:
            kw["TU"] = pikepdf.String(tu)
        field = pdf.make_indirect(pikepdf.Dictionary(**kw))
        field.P = page.obj
        field_refs.append(field)
    page.Annots = pikepdf.Array(field_refs)
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array(field_refs), NeedAppearances=True)

    out = BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def make_1x1_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    idat = zlib.compress(raw)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def make_docx(
    *,
    paragraphs: tuple[str, ...] = ("Hello world.",),
    image_count: int = 1,
    image_alt: tuple[str | None, ...] | None = None,
) -> bytes:
    """Build a minimal DOCX with `paragraphs` and `image_count` embedded 1x1 images.
    `image_alt`, when given (parallel to image_count), pre-sets each image's alt text
    via python-docx's inline shape `.alt_text` — None entries leave the image
    undescribed, the common starting point.
    """
    if image_alt is None:
        image_alt = (None,) * image_count
    assert len(image_alt) == image_count

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    png = make_1x1_png()
    for alt in image_alt:
        run = d.add_paragraph().add_run()
        pic = run.add_picture(BytesIO(png))
        if alt:
            pic._inline.docPr.set("descr", alt)

    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()
