"""OCR verification aid on the 1.1.1 alt-text card (<10s trust north star).

Alongside a vision draft, the reviewer gets the text OCR actually read from the image — a
deterministic cross-check of the description against what the image SAYS, instead of
squinting at a 96px thumbnail. A real measurement, never a score (ADR 0016); absent when
the image carries no text.
"""
from pathlib import Path


def test_suggest_route_attaches_ocr_text():
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "ai.py").read_text()
    suggest = src[src.index("def ai_suggest"):src.index("def ai_validate")]
    assert 'result["ocr_text"]' in suggest
    # only beside a REAL vision draft — a template gets no verification aid to "confirm"
    assert 'not result.get("is_template")' in suggest


def test_card_renders_the_aid_from_both_draft_paths():
    card = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "EvidenceCard.jsx").read_text()
    assert card.count("setOcrAid(r.ocr_text || null)") == 2   # draftWithAi + draftInstance
    assert card.count("text OCR-read from this image") == 2   # both render sites
