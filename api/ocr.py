"""1.4.5 / 1.4.9 Images of Text — OCR-based detection (ADR 0002 §agentic tier).

WCAG 1.4.5 (AA, Required): real text must be used rather than images of text,
except for a "Customizable" exception (the image can be visually re-styled to
the reader's needs) or an "Essential" exception (logotypes, brand names, a
screenshot where the exact presentation matters). WCAG 1.4.9 (AAA, Optional)
drops the Customizable exception — and since a static raster image embedded in
a document is never customizable to begin with, 1.4.9's real bite for documents
is that it tolerates none of the slack 1.4.5 gives small/incidental text blocks.
We model that honestly as a STRICTER threshold on the same OCR signal, not a
copy of 1.4.5 — 1.4.9 findings are a superset (every 1.4.5 hit reappears here,
plus smaller/shorter text blocks 1.4.5's higher floor lets through).

We can't tell from markup whether an image *contains* text, so this runs OCR
(tesseract) over the images actually embedded in a document and flags any that
carry a meaningful amount of text.

Scope: OOXML (docx/pptx/xlsx) and PDF, whose images are embedded and extractable
locally. HTML <img> references external files we don't fetch, so HTML isn't
covered here. The fix (re-authoring as real text) is human/AI-assisted, so a
finding is detected automatically and routed to review — never auto-passed.

Self-gating and bounded: returns [] when tesseract/pytesseract are unavailable
or ACP_DETECT_IMAGES_OF_TEXT=0, and never raises (OCR must not fail a scan).
Caps keep it cheap — small images (icons/bullets) and vector art are skipped, a
per-file image cap bounds runtime, and only images with >= a word threshold count
(so logos and one-word badges don't false-positive at the 1.4.5/AA bar).
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

# Tunables (env-overridable) — conservative defaults to avoid flagging logos.
_MIN_WORDS = int(os.environ.get("ACP_OCR_MIN_WORDS", "10"))     # >= this many real words = image of text (1.4.5/AA)
_MIN_PIXELS = int(os.environ.get("ACP_OCR_MIN_PIXELS", "20000"))  # skip icons/bullets (~140x140) (1.4.5/AA)
# 1.4.9/AAA has no Customizable exception to lean on — much lower floors, but
# still skip single-glyph/watermark noise (~35x35px, 3 words) rather than flag
# on literal pixel dust.
_MIN_WORDS_STRICT = int(os.environ.get("ACP_OCR_MIN_WORDS_STRICT", "3"))
_MIN_PIXELS_STRICT = int(os.environ.get("ACP_OCR_MIN_PIXELS_STRICT", "1200"))
_MAX_IMAGES = int(os.environ.get("ACP_OCR_MAX_IMAGES", "30"))    # per-file cap (bounds scan time)
_MAX_DIM = 3000  # downscale giant scans before OCR to keep memory/time bounded

_RASTER = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
_MEDIA_RE = re.compile(r"^(word|ppt|xl)/media/", re.I)
_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def is_available() -> bool:
    """True only when the OCR stack is actually usable — env-enabled, pytesseract
    importable, and the tesseract binary present."""
    if os.environ.get("ACP_DETECT_IMAGES_OF_TEXT", "1").lower() in ("0", "false", "no"):
        return False
    try:
        import pytesseract  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_words(img_bytes: bytes, min_pixels: int = _MIN_PIXELS) -> int:
    """Word count of text OCR'd from one image; 0 on any failure or if too small."""
    try:
        from PIL import Image
        import pytesseract
        im = Image.open(io.BytesIO(img_bytes))
        if (im.width * im.height) < min_pixels:
            return 0
        if max(im.width, im.height) > _MAX_DIM:
            scale = _MAX_DIM / max(im.width, im.height)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        text = pytesseract.image_to_string(im) or ""
        return len(_WORD_RE.findall(text))
    except Exception:
        return 0


def _ooxml_images(path: Path):
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if _MEDIA_RE.match(n) and n.lower().endswith(_RASTER):
                    try:
                        yield z.read(n)
                    except Exception:
                        continue
    except Exception:
        return


def _pdf_images(path: Path):
    try:
        import pikepdf
        with pikepdf.open(str(path)) as pdf:
            for page in pdf.pages:
                images = getattr(page, "images", {}) or {}
                for obj in images.values():
                    try:
                        pil = pikepdf.PdfImage(obj).as_pil_image()
                        buf = io.BytesIO()
                        pil.save(buf, format="PNG")
                        yield buf.getvalue()
                    except Exception:
                        continue
    except Exception:
        return


def _embedded_images(path: Path, ext: str) -> list[bytes]:
    """Materialize this document's embedded raster images once (bounded by
    _MAX_IMAGES) so 1.4.5 and 1.4.9 can both scan them without re-parsing the
    zip/PDF twice."""
    ext = ext.lower()
    if ext in (".docx", ".pptx", ".xlsx"):
        source = _ooxml_images(path)
    elif ext == ".pdf":
        source = _pdf_images(path)
    else:
        return []
    out = []
    for i, img in enumerate(source):
        if i >= _MAX_IMAGES:
            break
        out.append(img)
    return out


def images_of_text(path: Path, ext: str) -> list[dict]:
    """Return one 1.4.5 issue per embedded image that carries substantial text.
    Empty when OCR is unavailable/disabled — callers append these to the file's
    engine findings so they flow through the rubric and per-rule traces."""
    if not is_available():
        return []
    findings: list[dict] = []
    for img in _embedded_images(path, ext):
        if _ocr_words(img, _MIN_PIXELS) >= _MIN_WORDS:
            findings.append({
                "ruleId": "OCR_IMAGE_OF_TEXT",
                "wcag": "1.4.5 Images of Text",
                "severity": "SERIOUS",
            })
    return findings


def images_of_text_no_exception(path: Path, ext: str) -> list[dict]:
    """Return one 1.4.9 issue per embedded image whose OCR'd text clears the
    stricter AAA floor — genuinely more images than 1.4.5 catches, since AAA
    tolerates none of the incidental-text slack AA does. Same self-gating and
    bounds as images_of_text()."""
    if not is_available():
        return []
    findings: list[dict] = []
    for img in _embedded_images(path, ext):
        if _ocr_words(img, _MIN_PIXELS_STRICT) >= _MIN_WORDS_STRICT:
            findings.append({
                "ruleId": "OCR_IMAGE_OF_TEXT_STRICT",
                "wcag": "1.4.9 Images of Text (No Exception)",
                "severity": "MODERATE",
            })
    return findings
