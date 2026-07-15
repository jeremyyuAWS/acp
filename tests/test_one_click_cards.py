"""One-click deterministic cards — docx 1.4.8 (left-align) and pptx 1.4.2 (play-on-click).

Both fixes are exact and deterministic, but silently applying them would change layout or
authoring intent — so each is a pre-computed proposal the human elects. Gates mirror the
detectors exactly: below the justified floor / click-started audio yields nothing.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import proposals  # noqa: E402

_JP = '<w:p><w:pPr><w:jc w:val="both"/></w:pPr><w:r><w:t>Justified paragraph text.</w:t></w:r></w:p>'
_NP = "<w:p><w:r><w:t>Normal paragraph text.</w:t></w:r></w:p>"


def _docx(tmp: Path, body: str) -> Path:
    p = tmp / "d.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return p


def test_justified_docx_gets_one_election_card(tmp_path):
    out = proposals.propose_justified_fix(_docx(tmp_path, _JP * 4), ".docx")
    assert len(out) == 1
    assert out[0]["locator"] == "4 justified paragraph(s)"
    assert 'w:val="left"' in out[0]["proposed_value"]
    assert "deterministic" in out[0]["source"]


def test_below_detector_floor_yields_nothing(tmp_path):
    # 2 justified paragraphs < the detector's floor of 3 — no finding, no card.
    assert proposals.propose_justified_fix(_docx(tmp_path, _JP * 2 + _NP * 5), ".docx") == []


def _pptx(tmp: Path, timing: str) -> Path:
    slide = ('<p:sld><p:cSld><p:spTree><p:pic><a:audioFile r:link="rId2"/></p:pic>'
             f"</p:spTree></p:cSld><p:timing>{timing}</p:timing></p:sld>")
    p = tmp / "d.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/slides/slide1.xml", slide)
    return p


def test_autoplay_audio_gets_one_election_card(tmp_path):
    out = proposals.propose_autoplay_fix(_pptx(tmp_path, '<p:cond delay="0"/>'), ".pptx")
    assert len(out) == 1
    assert "play-on-click" in out[0]["proposed_value"]


def test_click_started_audio_yields_nothing(tmp_path):
    out = proposals.propose_autoplay_fix(
        _pptx(tmp_path, '<p:cond evt="onClick" delay="0"/>'), ".pptx")
    assert out == []


def test_wiring_and_capability():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert '"1.4.8", "Visual Presentation"' in src and '"1.4.2", "Audio Control"' in src
    import remediation_capability as cap
    assert cap.mode_for("docx", "1.4.8") == cap.ASSISTED
    assert cap.mode_for("pptx", "1.4.2") == cap.ASSISTED
