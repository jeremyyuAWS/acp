"""OCR must be bounded and must not read the same embedded image twice."""

import io

from PIL import Image

import ocr


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (240, 120), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_reuses_text_across_aa_and_aaa_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(ocr, "is_available", lambda: True)
    monkeypatch.setattr(ocr, "_OCR_TIMEOUT_S", 17)
    monkeypatch.setattr(ocr.pytesseract if hasattr(ocr, "pytesseract") else __import__("pytesseract"),
                        "image_to_string",
                        lambda _image, **kwargs: calls.append(kwargs) or "Readable text")
    with ocr._OCR_CACHE_LOCK:
        ocr._OCR_CACHE.clear()

    image = _png()
    assert ocr.ocr_text(image, min_pixels=20_000) == "Readable text"
    assert ocr.ocr_text(image, min_pixels=1_200) == "Readable text"
    assert calls == [{"timeout": 17}]


def test_ocr_timeout_is_a_nonfatal_empty_read(monkeypatch):
    import pytesseract

    monkeypatch.setattr(ocr, "is_available", lambda: True)
    monkeypatch.setattr(ocr, "_OCR_TIMEOUT_S", 1)
    monkeypatch.setattr(pytesseract, "image_to_string",
                        lambda _image, **_kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))
    with ocr._OCR_CACHE_LOCK:
        ocr._OCR_CACHE.clear()

    assert ocr.ocr_text(_png()) == ""
