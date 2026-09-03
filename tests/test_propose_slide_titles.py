"""pptx 2.4.6 slide-title drafts — AI names the slide from its own content.

Placement is already decided by the layout (the empty title placeholder the detector
flags); the model only drafts the name. Gates mirror office_structure's PPTX_TITLE_EMPTY
condition exactly; a filled title or a layout with no title slot yields nothing.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import proposals  # noqa: E402


def _slide(title_text: str | None, body: str) -> str:
    # Title-placeholder shape (matches office_structure._PPTX_TITLE_PH) + a body shape.
    title_sp = ""
    if title_text is not None:
        t = f"<a:r><a:t>{title_text}</a:t></a:r>" if title_text else ""
        title_sp = (f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                    f"<p:txBody><a:p>{t}</a:p></p:txBody></p:sp>")
    body_sp = (f"<p:sp><p:txBody><a:p><a:r><a:t>{body}</a:t></a:r></a:p></p:txBody></p:sp>")
    return f"<p:sld><p:cSld><p:spTree>{title_sp}{body_sp}</p:spTree></p:cSld></p:sld>"


def _pptx(tmp: Path, slides: list[str]) -> Path:
    p = tmp / "deck.pptx"
    with zipfile.ZipFile(p, "w") as z:
        for i, xml in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", xml)
    return p


def test_empty_title_gets_a_draft_from_the_slides_own_text(tmp_path, monkeypatch):
    import ai
    monkeypatch.setattr(ai, "model_is_available", lambda: True)
    monkeypatch.setattr(ai, "suggest_fix",
                        lambda *a, **k: {"suggestion": "Q2 Revenue by Region", "model": "llama3.2"})
    src = _pptx(tmp_path, [_slide("", "Revenue grew across all regions in the second quarter")])
    out = proposals.propose_slide_titles(src, ".pptx")
    assert len(out) == 1
    assert out[0]["locator"] == "slide 1"
    assert out[0]["proposed_value"] == "Q2 Revenue by Region"
    assert "Revenue grew across" in out[0]["rationale"]   # the slide's own words as evidence


def test_filled_title_and_no_placeholder_yield_nothing(tmp_path, monkeypatch):
    import ai
    monkeypatch.setattr(ai, "model_is_available", lambda: True)
    monkeypatch.setattr(ai, "suggest_fix", lambda *a, **k: {"suggestion": "X", "model": "m"})
    filled = _pptx(tmp_path, [_slide("Already titled", "Body text here")])
    assert proposals.propose_slide_titles(filled, ".pptx") == []
    d2 = tmp_path / "b"; d2.mkdir()
    no_slot = _pptx(d2, [_slide(None, "Blank-layout slide with no title slot at all")])
    assert proposals.propose_slide_titles(no_slot, ".pptx") == []


def test_ai_off_degrades_to_plain_review(tmp_path):
    src = _pptx(tmp_path, [_slide("", "Some body text on the slide")])
    assert proposals.propose_slide_titles(src, ".pptx", ai_enabled=False) == []


def test_wiring_and_capability():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert "propose_slide_titles" in src and '"2.4.6", "Headings and Labels"' in src
    import remediation_capability as cap
    assert cap.mode_for("pptx", "2.4.6") == cap.HUMAN    # pptx not in _STRUCTURE_LABEL_EXTS (xlsx only)
    assert cap.mode_for("pptx", "1.3.1") == cap.AUTO    # firstRow fixer, round-trip proven
