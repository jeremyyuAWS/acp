"""An image of text is transcribed, not described (WCAG 1.1.1 / F30).

Measured on 2026-07-29 against the real demo fixture — `demo-fixtures/word-accessibility-demo.docx`
`word/media/image2.png`, a white page reading "Quarterly Revenue Report 2026 / Total revenue
increased fourteen percent / across every regional business unit" — with the deployed vision
model (moondream, the only one baked into acp-ollama):

  before: 'A Quarterly Revenue Report for the year 2006, which shows that total revenue
           increased by 14% across all regional businesses.'
          ...the year wrong in 5/5 runs, "a chart or graph" invented, the FILENAME described as
          if it were visible content, and in one run the prompt's own "OCR:" marker leaked into
          the alt. OCR had read the text correctly every single time.
  after : the OCR text, verbatim, 5/5 identical, and ~3x faster (no model call).

The guard has to stay conservative in both directions, which is what these tests pin: a CHART
still wants a description ('bar chart comparing …'), because transcribing its axis labels would
be worse than a paraphrase; and the PDF remediator must never transcribe, because it OCRs a
render of the whole PAGE — prose there means "the page has paragraphs", not "this figure is an
image of text".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402

PROSE = ("Quarterly Revenue Report 2026 Total revenue increased fourteen percent "
         "across every regional business unit")


# ── the discriminator ──────────────────────────────────────────────────────────

def test_connected_prose_is_an_image_of_text():
    assert ai._looks_like_an_image_of_text(PROSE) is True
    assert ai._looks_like_an_image_of_text("Safety first. Report every incident immediately.") is True


def test_chart_furniture_is_not_an_image_of_text():
    """Axis labels and legends are fragments, not prose — a chart needs a DESCRIPTION."""
    assert ai._looks_like_an_image_of_text("North 150 South 90 East 210 West 60") is False
    assert ai._looks_like_an_image_of_text("0 25 50 75 100 Q1 Q2 Q3 Q4") is False
    assert ai._looks_like_an_image_of_text("% $ 2026 12.5 3.4") is False


def test_too_little_text_is_not_an_image_of_text():
    assert ai._looks_like_an_image_of_text("") is False
    assert ai._looks_like_an_image_of_text("Sales") is False
    assert ai._looks_like_an_image_of_text("Total revenue") is False


def test_transcription_collapses_whitespace_and_bounds_length():
    assert ai._transcribed_alt("  Quarterly   Revenue\n Report  ") == "Quarterly Revenue Report"
    long = " ".join(["word"] * 200)
    out = ai._transcribed_alt(long)
    assert len(out) <= 251 and out.endswith("…")


# ── the structured path ────────────────────────────────────────────────────────

def _no_model(monkeypatch):
    """Fail loudly if the vision model is consulted — the point is that it is not."""
    def boom(*a, **k):
        raise AssertionError("the vision model must not be called for an image of text")
    monkeypatch.setattr(ai, "_vision_generate", boom)


def _ocr(monkeypatch, text):
    import ocr as _ocr
    monkeypatch.setattr(_ocr, "ocr_text", lambda *a, **k: text)


def test_an_image_of_text_is_transcribed_verbatim_with_no_model_call(monkeypatch):
    _ocr(monkeypatch, PROSE)
    _no_model(monkeypatch)
    out = ai.describe_image_structured(b"\x89PNG fake", filename="demo.docx",
                                       allow_transcription=True)
    assert out is not None
    assert out["alt"] == PROSE                  # verbatim — the year cannot drift to 2006
    assert out["grounded"] is True
    assert out["source"] == "ocr"
    assert out["model"] is None                 # no model ran, so none may be claimed
    assert "verbatim" in out["evidence"]
    assert "OCR:" not in out["alt"]             # the prompt marker cannot leak; there is no prompt


def test_a_chart_still_gets_a_model_description(monkeypatch):
    _ocr(monkeypatch, "North 150 South 90 East 210 West 60")
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "Bar chart comparing regional sales")
    out = ai.describe_image_structured(b"\x89PNG fake", filename="demo.docx",
                                       allow_transcription=True)
    assert out["alt"] == "Bar chart comparing regional sales"
    assert out.get("source") is None
    assert out["model"] == ai.OLLAMA_VISION_MODEL


def test_the_pdf_page_render_path_never_transcribes(monkeypatch):
    """allow_transcription defaults to False: a page of prose must not become a figure's alt."""
    _ocr(monkeypatch, PROSE)
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "Chart of quarterly revenue")
    out = ai.describe_image_structured(b"\x89PNG fake", filename="report.pdf")
    assert out["alt"] == "Chart of quarterly revenue"
    assert out.get("source") is None


def test_no_ocr_text_is_still_an_ungrounded_guess(monkeypatch):
    _ocr(monkeypatch, "")
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "A dog on a beach")
    monkeypatch.setattr(ai, "_escalate_vision", lambda *a, **k: None)
    out = ai.describe_image_structured(b"\x89PNG fake", filename="demo.docx",
                                       allow_transcription=True)
    assert out["grounded"] is False and out.get("source") is None


# ── provenance must not claim a model that did not run ─────────────────────────

def test_office_provenance_does_not_claim_a_vision_model_for_a_transcription():
    src = (Path(__file__).resolve().parent.parent / "api" / "remediate_office.py").read_text()
    block = src[src.index('rule_id": "SC_1_1_1"') - 900:src.index('rule_id": "SC_1_1_1"') + 900]
    assert 'res.get("source") == "ocr"' in src
    assert "read by OCR and transcribed verbatim" in block
    # the old unconditional interpolation would render "AI vision model (None)"
    assert "transcribed" in block


def test_office_remediator_opts_into_transcription_and_pdf_does_not():
    api = Path(__file__).resolve().parent.parent / "api"
    assert "allow_transcription=True" in (api / "remediate_office.py").read_text()
    assert "allow_transcription" not in (api / "remediate_pdf.py").read_text()
