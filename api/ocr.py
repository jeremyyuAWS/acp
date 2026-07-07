"""1.4.5 Images of Text — OCR-based detection (ADR 0002 §agentic tier).

WCAG 1.4.5 (AA, Required): real text must be used rather than images of text
(logos / essential images excepted). We can't tell from markup whether an image
*contains* text, so this runs OCR (tesseract) over the images actually embedded
in a document and flags any that carry a meaningful amount of text.

Scope: OOXML (docx/pptx/xlsx) and PDF, whose images are embedded and extractable
locally. HTML <img> references external files we don't fetch, so HTML isn't
covered here. The fix (re-authoring as real text) is human/AI-assisted, so a
finding is detected automatically and routed to review — never auto-passed.

Self-gating and bounded: returns [] when tesseract/pytesseract are unavailable
or ACP_DETECT_IMAGES_OF_TEXT=0, and never raises (OCR must not fail a scan).
Caps keep it cheap — small images (icons/bullets) and vector art are skipped, a
per-file image cap bounds runtime, and only images with >= a word threshold count
(so logos and one-word badges don't false-positive).
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

# Tunables (env-overridable) — conservative defaults to avoid flagging logos.
_MIN_WORDS = int(os.environ.get("ACP_OCR_MIN_WORDS", "10"))     # >= this many real words = image of text
_MIN_PIXELS = int(os.environ.get("ACP_OCR_MIN_PIXELS", "20000"))  # skip icons/bullets (~140x140)
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


def _ocr_words(img_bytes: bytes) -> int:
    """Word count of text OCR'd from one image; 0 on any failure or if too small."""
    try:
        from PIL import Image
        import pytesseract
        im = Image.open(io.BytesIO(img_bytes))
        if (im.width * im.height) < _MIN_PIXELS:
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


def images_of_text(path: Path, ext: str) -> list[dict]:
    """Return one 1.4.5 issue per embedded image that carries substantial text.
    Empty when OCR is unavailable/disabled — callers append these to the file's
    engine findings so they flow through the rubric and per-rule traces."""
    if not is_available():
        return []
    ext = ext.lower()
    if ext in (".docx", ".pptx", ".xlsx"):
        source = _ooxml_images(path)
    elif ext == ".pdf":
        source = _pdf_images(path)
    else:
        return []
    findings: list[dict] = []
    for i, img in enumerate(source):
        if i >= _MAX_IMAGES:
            break
        if _ocr_words(img) >= _MIN_WORDS:
            findings.append({
                "ruleId": "OCR_IMAGE_OF_TEXT",
                "wcag": "1.4.5 Images of Text",
                "severity": "SERIOUS",
            })
    return findings
