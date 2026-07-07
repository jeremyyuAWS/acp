"""1.4.5 / 1.4.9 images-of-text OCR detection (api/ocr.py).

OCR round-trips are skipped when tesseract isn't installed (e.g. CI without the
apt package) — the gating + non-OCR behaviour is always exercised.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import ocr  # noqa: E402

needs_tesseract = pytest.mark.skipif(not ocr.is_available(), reason="tesseract not installed")


def _png(text: str | None, size=(800, 220), color="white") -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, color)
    if text:
        ImageDraw.Draw(im).multiline_text((15, 15), text, fill="black", spacing=8)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _docx(tmp: Path, *images: bytes) -> Path:
    p = tmp / "deck.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        for i, img in enumerate(images):
            z.writestr(f"word/media/image{i + 1}.png", img)
    return p


_PARAGRAPH = ("The quick brown fox jumps over\nthe lazy dog while twelve\n"
              "wizards make jolted vows today")


@needs_tesseract
def test_flags_image_of_text(tmp_path):
    findings = ocr.images_of_text(_docx(tmp_path, _png(_PARAGRAPH)), ".docx")
    assert len(findings) == 1
    assert findings[0]["wcag"].startswith("1.4.5")
    assert findings[0]["ruleId"] == "OCR_IMAGE_OF_TEXT"


@needs_tesseract
def test_ignores_textless_image(tmp_path):
    assert ocr.images_of_text(_docx(tmp_path, _png(None, color="skyblue")), ".docx") == []


@needs_tesseract
def test_ignores_tiny_icon(tmp_path):
    # Below the pixel floor even if it had text — icons/bullets must not flag.
    assert ocr.images_of_text(_docx(tmp_path, _png(_PARAGRAPH, size=(80, 80))), ".docx") == []


@needs_tesseract
def test_one_finding_per_text_image(tmp_path):
    doc = _docx(tmp_path, _png(_PARAGRAPH), _png(None, color="white"), _png(_PARAGRAPH))
    assert len(ocr.images_of_text(doc, ".docx")) == 2


def test_unsupported_ext_returns_empty(tmp_path):
    (tmp_path / "x.txt").write_text("hi")
    assert ocr.images_of_text(tmp_path / "x.txt", ".txt") == []


def test_env_disable_gates_off(monkeypatch):
    monkeypatch.setenv("ACP_DETECT_IMAGES_OF_TEXT", "0")
    assert ocr.is_available() is False
    # disabled → no work, empty result even for a supported type
    assert ocr.images_of_text(Path("whatever.docx"), ".docx") == []
    assert ocr.images_of_text_no_exception(Path("whatever.docx"), ".docx") == []


# ── 1.4.9 (AAA, No Exception) — stricter floor, genuinely a superset of 1.4.5 ──

@needs_tesseract
def test_1_4_9_catches_a_small_short_text_image_1_4_5_misses(tmp_path):
    # 220x80px (17,600px) with 4 words: clears 1.4.9's floor (3 words / 1200px)
    # but sits below 1.4.5's AA floor (10 words / 20,000px) — proves 1.4.9 is a
    # genuinely stricter check, not an alias of 1.4.5.
    img = _png("Save twenty percent today", size=(220, 80))
    doc = _docx(tmp_path, img)
    strict = ocr.images_of_text_no_exception(doc, ".docx")
    lenient = ocr.images_of_text(doc, ".docx")
    assert len(strict) == 1 and strict[0]["wcag"].startswith("1.4.9")
    assert lenient == []


@needs_tesseract
def test_1_4_9_still_ignores_textless_and_tiny_images(tmp_path):
    assert ocr.images_of_text_no_exception(_docx(tmp_path, _png(None, color="skyblue")), ".docx") == []
    assert ocr.images_of_text_no_exception(_docx(tmp_path, _png(_PARAGRAPH, size=(20, 20))), ".docx") == []


@needs_tesseract
def test_1_4_9_also_flags_full_1_4_5_violations(tmp_path):
    # A real block of text (the 1.4.5 fixture) must still fail the stricter check.
    doc = _docx(tmp_path, _png(_PARAGRAPH))
    assert len(ocr.images_of_text_no_exception(doc, ".docx")) == 1
    assert len(ocr.images_of_text(doc, ".docx")) == 1
