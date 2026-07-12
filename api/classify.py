"""Lightweight document classification (ADR 0020 stage 2 — the Discover-side inventory).

Answers "what IS this?" — NOT "what's wrong with it?" (that stays Assess). A cheap container
peek only: page/slide/sheet counts, an embedded-image count, and has-text / has-images /
looks-scanned booleans, rolled into a plain-English document class. NO WCAG rule runs here,
nothing is downloaded, and it never raises — a file that can't be peeked classifies as
'unknown', not a failed scan.

The honest line this draws (ADR 0020): reading a slide count or seeing that a deck *contains*
images is inventory; deciding those images *lack alt text* is conformance. This module stays
strictly on the inventory side.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_RASTER = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".emf", ".wmf")
_SLIDE = re.compile(r"^ppt/slides/slide\d+\.xml$")
_SHEET = re.compile(r"^xl/worksheets/sheet\d+\.xml$")
_MEDIA = re.compile(r"^(word|ppt|xl)/media/", re.I)
_A_T = re.compile(rb"<a:t[ >]|<w:t[ >]")   # any drawn/word text run — cheap has-text probe


def _ooxml(path: Path, ext: str) -> dict:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        images = sum(1 for n in names if _MEDIA.match(n) and n.lower().endswith(_RASTER))
        slides = sum(1 for n in names if _SLIDE.match(n))
        sheets = sum(1 for n in names if _SHEET.match(n))
        # has_text: peek the body part(s) for a text run — bounded, first match wins.
        has_text = False
        body_parts = [n for n in names if n in ("word/document.xml",)
                      or _SLIDE.match(n) or _SHEET.match(n)][:20]
        for n in body_parts:
            try:
                if _A_T.search(z.read(n)):
                    has_text = True
                    break
            except Exception:
                continue
    pages = slides or (sheets or None)      # docx page count isn't stored in the file → None
    return {"pages": pages, "images": images, "sheets": sheets or None,
            "has_text": has_text, "has_images": images > 0, "is_scanned": False}


def _pdf(path: Path) -> dict:
    """Page count + an image-vs-text peek. is_scanned ≈ pages carry images but almost no
    extractable text (a scanned/photographed document). Bounded to the first pages."""
    pages = images = 0
    text_len = 0
    try:
        import pikepdf
        with pikepdf.open(str(path)) as pdf:
            pages = len(pdf.pages)
            for pg in list(pdf.pages)[:10]:
                imgs = getattr(pg, "images", {}) or {}
                images += len(imgs)
    except Exception:
        pass
    try:
        import pdfminer.high_level as _hl
        text_len = len((_hl.extract_text(str(path), maxpages=5) or "").strip())
    except Exception:
        text_len = 0
    is_scanned = bool(pages and images and text_len < 40 * max(1, min(pages, 5)))
    return {"pages": pages or None, "images": images, "sheets": None,
            "has_text": text_len > 0, "has_images": images > 0, "is_scanned": is_scanned}


def _doc_class(ext: str, m: dict) -> str:
    if m.get("is_scanned"):
        return "scanned-pdf"
    if ext == ".pptx":
        return "slide-deck"
    if ext == ".xlsx":
        return "spreadsheet"
    if ext == ".pdf":
        return "pdf-document"
    if ext == ".docx":
        return "image-heavy-document" if (m.get("images") or 0) >= 5 else "text-document"
    if ext in (".html", ".htm"):
        return "web-page"
    return "document"


def classify_from_metadata(name: str, mime: str | None = None) -> dict:
    """Metadata-only inventory classification (ADR 0020 — Discover without opening the file).

    Derives doc_class from the file extension / Drive mime type ALONE — no bytes read, so a
    Discover phase can classify a whole estate in milliseconds. The detailed counts (pages,
    images, sheets, is_scanned) that need the container stay null here; they are filled at
    Assess by classify() when the file is actually opened. Never raises."""
    ext = Path(name or "").suffix.lower()
    m = (mime or "").lower()
    base = {"pages": None, "images": None, "sheets": None, "has_text": False,
            "has_images": False, "is_scanned": False, "doc_class": "unknown"}
    if ext == ".pptx" or "presentation" in m:
        base["doc_class"] = "slide-deck"
    elif ext == ".xlsx" or "spreadsheet" in m:
        base["doc_class"] = "spreadsheet"
    elif ext == ".pdf" or m == "application/pdf":
        base["doc_class"] = "pdf-document"
    elif ext == ".docx" or ("word" in m and "document" in m):
        base["doc_class"] = "text-document"
    elif ext in (".html", ".htm") or "html" in m:
        base["doc_class"] = "web-page"
    return base


def classify(path: Path, ext: str) -> dict:
    """Inventory metadata for one file: {pages, images, sheets, has_text, has_images,
    is_scanned, doc_class}. Cheap, deterministic, never raises. Returns a doc_class of
    'unknown' with null/false fields for a format we don't peek or a file we can't open."""
    ext = (ext or "").lower()
    base = {"pages": None, "images": 0, "sheets": None, "has_text": False,
            "has_images": False, "is_scanned": False, "doc_class": "unknown"}
    try:
        if ext in (".docx", ".pptx", ".xlsx"):
            m = _ooxml(path, ext)
        elif ext == ".pdf":
            m = _pdf(path)
        elif ext in (".html", ".htm"):
            raw = Path(path).read_bytes()
            m = {"pages": 1, "images": raw.count(b"<img"), "sheets": None,
                 "has_text": len(re.sub(rb"<[^>]+>", b"", raw).strip()) > 0,
                 "has_images": b"<img" in raw, "is_scanned": False}
        else:
            return base
    except Exception:
        return base
    m["doc_class"] = _doc_class(ext, m)
    return {**base, **m}
