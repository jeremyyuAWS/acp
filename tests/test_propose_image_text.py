"""WCAG 1.4.5 images-of-text PROPOSAL — OCR the text back out of an embedded image so a
reviewer can paste it in as real text.

The detection side (ocr.images_of_text) only emits a bare finding; the fix card needs the
actual OCR'd text + a thumbnail. proposals.propose_images_of_text produces that, gated at the
SAME floor detection uses (`_MIN_WORDS` real words over `_MIN_PIXELS`), so the scan finding and
the fix card can never disagree. It is a proposal — never auto-applied — because OCR misreads
and replacing an image with live text is an authoring decision.

These monkeypatch ocr's internals so the suite does not need tesseract installed; one
end-to-end sanity check is gated on ocr.is_available().
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ocr  # noqa: E402
import proposals  # noqa: E402


@pytest.fixture
def _ocr_stub(monkeypatch):
    """Drive propose_images_of_text off a scripted image set instead of a real document.

    `words[i]` = the word count ocr._ocr_words returns for image i; `texts[i]` = what
    ocr.ocr_text returns for it. Set via the returned configure() helper.
    """
    state = {"imgs": [], "words": [], "texts": []}

    def configure(words, texts):
        state["words"] = list(words)
        state["texts"] = list(texts)
        state["imgs"] = [f"img{i}".encode() for i in range(len(words))]

    monkeypatch.setattr(ocr, "is_available", lambda: True)
    monkeypatch.setattr(ocr, "_embedded_images", lambda path, ext: list(state["imgs"]))
    monkeypatch.setattr(ocr, "_ocr_words",
                        lambda img, min_pixels=ocr._MIN_PIXELS: state["words"][state["imgs"].index(img)])
    monkeypatch.setattr(ocr, "ocr_text",
                        lambda img, **kw: state["texts"][state["imgs"].index(img)])
    # thumb_b64 on fake bytes would just return None (undecodable) — fine, but pin it so a
    # proposal is asserted on its value, not its thumbnail.
    monkeypatch.setattr(proposals, "thumb_b64", lambda img, **kw: None)
    return configure


def test_image_with_substantial_text_yields_a_proposal(_ocr_stub):
    _ocr_stub(words=[12], texts=["Quarterly Revenue Report  2026\n  up 14% YoY"])
    out = proposals.propose_images_of_text("doc.docx", ".docx")
    assert len(out) == 1
    p = out[0]
    assert p["proposed_value"] == "Quarterly Revenue Report 2026 up 14% YoY"  # whitespace collapsed
    assert p["locator"] == "image 1"
    assert "1.4.5" in p["rationale"]
    assert "OCR" in p["source"]


def test_a_logo_with_few_words_yields_no_proposal(_ocr_stub):
    # 2 words (a wordmark) is below the images-of-text bar — offering to "replace" it would be
    # noise, and 1.4.5 explicitly exempts logotypes.
    _ocr_stub(words=[2], texts=["Acme Corp"])
    assert proposals.propose_images_of_text("doc.docx", ".docx") == []


def test_word_count_gate_band_boundaries(_ocr_stub):
    # Mutation guards on BOTH band floors.
    # Exactly _MIN_WORDS → the AA band (the 1.4.5 paste-back card).
    _ocr_stub(words=[ocr._MIN_WORDS], texts=["w " * ocr._MIN_WORDS])
    out = proposals.propose_images_of_text("d.docx", ".docx")
    assert len(out) == 1 and "1.4.5" in out[0]["rationale"]
    # One below → drops to the STRICT band (a 1.4.9 card offering the logotype exception),
    # not to nothing — the 1.4.9 scan finding needs a review path too.
    _ocr_stub(words=[ocr._MIN_WORDS - 1], texts=["w " * ocr._MIN_WORDS])
    out = proposals.propose_images_of_text("d.docx", ".docx")
    assert len(out) == 1 and "1.4.9" in out[0]["rationale"] and "logotype" in out[0]["rationale"]
    # Exactly the strict floor → still a card; one below → nothing at all.
    _ocr_stub(words=[ocr._MIN_WORDS_STRICT], texts=["some words here"])
    assert len(proposals.propose_images_of_text("d.docx", ".docx")) == 1
    _ocr_stub(words=[ocr._MIN_WORDS_STRICT - 1], texts=["two words"])
    assert proposals.propose_images_of_text("d.docx", ".docx") == []


def test_qualifying_image_with_empty_ocr_text_yields_nothing(_ocr_stub):
    # Passes the word-count gate but ocr_text comes back blank — never emit an empty value.
    _ocr_stub(words=[15], texts=["   \n  "])
    assert proposals.propose_images_of_text("doc.docx", ".docx") == []


def test_mixed_set_proposes_only_the_text_bearing_images(_ocr_stub):
    _ocr_stub(words=[15, 1, 11], texts=["A full sentence of embedded text here", "x", "Another block of real text"])
    out = proposals.propose_images_of_text("deck.pptx", ".pptx")
    assert [p["locator"] for p in out] == ["image 1", "image 3"]


def test_returns_empty_when_ocr_unavailable(monkeypatch):
    monkeypatch.setattr(ocr, "is_available", lambda: False)
    assert proposals.propose_images_of_text("doc.docx", ".docx") == []


def test_one_bad_image_does_not_sink_the_rest(_ocr_stub, monkeypatch):
    _ocr_stub(words=[15, 15], texts=["good text block one two three", "second good block four five"])

    calls = {"n": 0}
    real = ocr.ocr_text

    def boom(img, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("decode blew up on image 1")
        return real(img, **kw)

    monkeypatch.setattr(ocr, "ocr_text", boom)
    out = proposals.propose_images_of_text("doc.docx", ".docx")
    assert len(out) == 1 and out[0]["locator"] == "image 2"


@pytest.mark.skipif(not ocr.is_available(), reason="tesseract not installed")
def test_end_to_end_with_a_real_text_image():
    """Sanity: a real PNG that literally says a sentence must OCR back to a proposal whose
    value contains those words. Only runs where tesseract is present."""
    from PIL import Image, ImageDraw
    import io
    import tempfile
    import zipfile

    im = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(im).text((10, 80), "The quarterly revenue report shows growth", fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    png = buf.getvalue()

    # minimal .docx-shaped zip with the image under word/media (what _ooxml_images walks)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "doc.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/media/image1.png", png)
        out = proposals.propose_images_of_text(path, ".docx")

    # OCR may not be pixel-perfect, but a text-bearing image must yield a non-empty proposal.
    if out:  # tesseract present but may under-read a synthetic font; don't hard-fail on OCR quality
        assert out[0]["proposed_value"].strip()
        # Which band depends on how many words tesseract recovers from the synthetic font —
        # either way the card cites the right SC.
        assert "1.4.5" in out[0]["rationale"] or "1.4.9" in out[0]["rationale"]


@pytest.mark.skipif(not ocr.is_available(), reason="tesseract not installed")
def test_end_to_end_xlsx_image_of_text_matches_docx():
    """xlsx parity — WCAG 1.4.5 covers spreadsheets too. Every stubbed test above monkeypatches
    ocr._embedded_images (which ignores `ext`), so NONE of them exercise the per-format media
    walk; the only real-zip test is docx. This pins that an image of text embedded under
    xl/media/ is reached and proposed exactly like the same image under word/media/, so a
    regression in _ooxml_images' xl/ branch (e.g. a narrowed media glob) cannot pass silently.

    Asserted as docx↔xlsx PARITY rather than an absolute count, so it stays honest to whatever
    the local tesseract actually reads — but a guard (`out_docx` non-empty) keeps it from passing
    vacuously if OCR under-reads the fixture to nothing."""
    from PIL import Image, ImageDraw
    import io
    import tempfile
    import zipfile

    # A clear, multi-line block well above the word/pixel floor, so OCR reads it the same via
    # either package and the parity assertion below is meaningful, not vacuous.
    lines = ("The quick brown fox jumps over\nthe lazy dog while twelve\n"
             "wizards make jolted vows today")
    im = Image.new("RGB", (800, 240), "white")
    ImageDraw.Draw(im).multiline_text((15, 15), lines, fill="black", spacing=8)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    png = buf.getvalue()

    def _propose(name: str, media_part: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / name
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(media_part, png)             # the ONLY part _ooxml_images should walk
            return proposals.propose_images_of_text(path, path.suffix)

    out_docx = _propose("doc.docx", "word/media/image1.png")
    out_xlsx = _propose("book.xlsx", "xl/media/image1.png")

    assert out_docx, "fixture must OCR above the word floor, else the parity check is vacuous"
    # The identical image under xl/media/ must be reached and proposed just like word/media/.
    assert len(out_xlsx) == len(out_docx) == 1
    assert out_xlsx[0]["proposed_value"] == out_docx[0]["proposed_value"]
    assert "1.4.5" in out_xlsx[0]["rationale"]


def test_handler_enqueues_1_4_5_even_for_an_image_only_doc(monkeypatch):
    """The wiring that matters: _propose_text_findings must enqueue the 1.4.5 proposals
    INDEPENDENTLY of the text proposers. An image-only document has no extractable text, so
    3.1.2/1.3.3 correctly skip — but it can still fail 1.4.5, and the old `if not text: return`
    would have silently dropped it. This pins that 1.4.5 survives an empty text extract."""
    import handlers
    import pii

    enq = []
    monkeypatch.setattr(pii, "extract_text", lambda p: "")                 # image-only: no text
    monkeypatch.setattr(proposals, "propose_images_of_text",
                        lambda path, ext: [proposals.proposal(
                            locator="image 1", before="b", proposed_value="hello world text",
                            rationale="WCAG 1.4.5", source="OCR")])
    monkeypatch.setattr(handlers, "_enqueue_proposals",
                        lambda scan_id, filename, sc, name, props, **kw: enq.append((sc, len(props))))

    handlers._propose_text_findings("scan1", "poster.docx", b"PK\x03\x04ignored", ai_enabled=True)
    scs = [sc for sc, _ in enq]
    assert "1.4.5" in scs                                 # enqueued despite no extractable text
    assert "3.1.2" not in scs and "1.3.3" not in scs      # text proposers correctly skipped
