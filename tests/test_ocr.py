"""1.4.5 images-of-text OCR detection (api/ocr.py).

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
