"""Page-1 raster preview for a document (ADR 0015).

A pure, dependency-light renderer: bytes in, PNG bytes out — no DB, no FastAPI, no
network, so it unit-tests against a corpus file directly. The owner-check, source-byte
resolution, and blob caching live in the endpoint (routes/scans.py); this module only
turns a document's bytes into a thumbnail.

Renderer: pypdfium2 (Google's pdfium — BSD-3-Clause/Apache-2.0, permissive; a pure pip
wheel bundling the binary, already pulled in transitively by pdfplumber). Pillow encodes
the bitmap to PNG. PyMuPDF (AGPL) and poppler (GPL, via pdf2image) are deliberately avoided
— see ADR 0015.

Contract: render_page1_png NEVER raises. Any failure — unsupported type, corrupt or
encrypted PDF, a pdfium error — returns None, so a missing thumbnail can never break scan,
remediate, or report.
"""
from __future__ import annotations
import io

# Longest-edge cap for the output PNG. A page-1 preview, not a viewer — this keeps the
# cached object to tens of KB and is ample for the HITL surfaces and the certification PDF.
_MAX_EDGE = 1000
# pdfium renders at 72*scale DPI; 2.0 → 144 DPI, enough to downscale from cleanly.
_RENDER_SCALE = 2.0

# Extensions this module can rasterize today. Office (docx/pptx/xlsx) is a phase-2 follow-on
# (ADR 0015) — callers get None and degrade to a placeholder.
RENDERABLE_EXTS = (".pdf",)


def can_render(ext: str) -> bool:
    """Whether render_page1_png can (attempt to) rasterize this extension."""
    return (ext or "").lower() in RENDERABLE_EXTS


def render_page1_png(data: bytes, ext: str) -> bytes | None:
    """Render page 1 of a document to a PNG, downscaled to _MAX_EDGE on the long side.

    Returns the PNG bytes, or None for anything we can't render (non-PDF, empty, corrupt,
    encrypted, or any pdfium/Pillow error). Never raises — a thumbnail is best-effort."""
    if not data or not can_render(ext):
        return None
    try:
        return _render_pdf_page1(data)
    except Exception:
        # Corrupt bytes, password-protected PDF, pdfium load failure, Pillow encode error —
        # all collapse to "no thumbnail". Intentionally broad: this must never propagate.
        return None


def _render_pdf_page1(data: bytes) -> bytes | None:
    import pypdfium2 as pdfium
    from PIL import Image

    pdf = pdfium.PdfDocument(data)  # raises on encrypted/corrupt — caught by render_page1_png
    try:
        if len(pdf) == 0:
            return None
        bitmap = pdf[0].render(scale=_RENDER_SCALE)
        img = bitmap.to_pil().convert("RGB")
    finally:
        pdf.close()

    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_EDGE:
        ratio = _MAX_EDGE / longest
        img = img.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
