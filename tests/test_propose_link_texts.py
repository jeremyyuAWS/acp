"""Office link-text proposer (2.4.4/2.4.9, docx + pptx) — the html lane ported to OOXML.

A vague link ("click here", bare URL) or one whose display text is reused for a different
destination gets a descriptive-text proposal: deterministic derivation from the target when
possible, AI draft otherwise (skipped keyless). Extraction reuses the 2.4.9 detector's own
regexes, so proposer and detector see identical links. Self-gating: descriptive, unique
links yield nothing.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import proposals  # noqa: E402

_RELS = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{}</Relationships>"""
_REL = '<Relationship Id="{}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{}" TargetMode="External"/>'


def _docx(tmp: Path, body: str, rels: str) -> Path:
    p = tmp / "d.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
        z.writestr("word/_rels/document.xml.rels", _RELS.format(rels))
    return p


def _pptx(tmp: Path, slide: str, rels: str) -> Path:
    p = tmp / "d.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/slides/slide1.xml", slide)
        z.writestr("ppt/slides/_rels/slide1.xml.rels", _RELS.format(rels))
    return p


def _link(rid: str, text: str) -> str:
    return f'<w:hyperlink r:id="{rid}"><w:r><w:t>{text}</w:t></w:r></w:hyperlink>'


def test_vague_docx_link_gets_derived_text(tmp_path):
    src = _docx(tmp_path, _link("rId1", "click here"),
                _REL.format("rId1", "https://example.com/reports/Annual-Report-2026.pdf"))
    out = proposals.propose_link_texts(src, ".docx", ai_enabled=False)
    assert len(out) == 1
    p = out[0]
    assert p["sc"] == "2.4.4"
    assert "Annual Report 2026" in p["proposed_value"]      # derived from the target, no AI
    assert p["before"] == "click here"
    assert "derived from the link target" in p["source"]


def test_reused_text_different_destinations_is_249(tmp_path):
    body = (_link("rId1", "Read the policy") + _link("rId2", "Read the policy"))
    rels = (_REL.format("rId1", "https://example.com/policies/privacy-policy") +
            _REL.format("rId2", "https://example.com/policies/refund-policy"))
    out = proposals.propose_link_texts(_docx(tmp_path, body, rels), ".docx", ai_enabled=False)
    assert {p["sc"] for p in out} == {"2.4.9"}
    assert len(out) == 2                                    # one proposal PER destination
    assert {p["proposed_value"] for p in out} == {"Privacy Policy", "Refund Policy"}


def test_descriptive_unique_links_yield_nothing(tmp_path):
    src = _docx(tmp_path, _link("rId1", "Download the 2026 benefits enrollment guide"),
                _REL.format("rId1", "https://example.com/benefits-guide.pdf"))
    assert proposals.propose_link_texts(src, ".docx", ai_enabled=False) == []


def test_pptx_links_extracted_from_runs(tmp_path):
    slide = ('<p:sld><p:txBody><a:p><a:r><a:rPr><a:hlinkClick r:id="rId1"/></a:rPr>'
             "<a:t>here</a:t></a:r></a:p></p:txBody></p:sld>")
    src = _pptx(tmp_path, slide, _REL.format("rId1", "https://example.com/team/leadership-team"))
    out = proposals.propose_link_texts(src, ".pptx", ai_enabled=False)
    assert len(out) == 1 and out[0]["sc"] == "2.4.4"
    assert out[0]["proposed_value"] == "Leadership Team"


def test_handler_routes_both_scs():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert "propose_link_texts" in src
    assert '"2.4.4", "Link Purpose (In Context)"' in src
    assert '"2.4.9", "Link Purpose (Link Only)"' in src


def test_capability_promoted():
    import remediation_capability as cap
    for fmt in ("docx", "pptx"):
        assert cap.CAPABILITY[fmt]["2.4.4"] == cap.ASSISTED
        assert cap.CAPABILITY[fmt]["2.4.9"] == cap.ASSISTED
