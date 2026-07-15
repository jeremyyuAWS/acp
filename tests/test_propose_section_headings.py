"""docx 2.4.10 section-heading proposals — AI names the document's OWN sections.

Sectioning is an authoring decision, so nothing is auto-inserted: the document is split at
its own blank-paragraph boundaries (the model never invents where sections are), the model
only drafts a name per section, and every proposal carries the section's opening words as
evidence. Gates mirror the detector exactly (no Heading styles + its paragraph floor), so a
card can never appear for a document the scan didn't flag.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import proposals  # noqa: E402

_P = "<w:p><w:r><w:t>{}</w:t></w:r></w:p>"
_EMPTY = "<w:p></w:p>"
_LONG = ("This paragraph carries enough real prose words that the section it belongs to "
         "clears the minimum-words floor used by the proposer for a nameable section.")


def _docx(tmp: Path, body: str) -> Path:
    p = tmp / "d.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return p


def _headingless(tmp, sections=3, paras_per=6):
    body = _EMPTY.join("".join(_P.format(f"{_LONG} s{s}p{i}") for i in range(paras_per))
                       for s in range(sections))
    return _docx(tmp, body)


def test_sections_come_from_the_documents_own_boundaries(tmp_path, monkeypatch):
    import ai
    monkeypatch.setattr(ai, "is_available", lambda: True)
    titles = iter(["Enrollment Overview", "Coverage Details", "How To File A Claim"])
    monkeypatch.setattr(ai, "suggest_fix",
                        lambda *a, **k: {"suggestion": next(titles), "model": "llama3.2"})
    out = proposals.propose_section_headings(_headingless(tmp_path), ".docx")
    assert [p["proposed_value"] for p in out] == [
        "Enrollment Overview", "Coverage Details", "How To File A Claim"]
    assert out[0]["locator"] == "before paragraph 1"     # placement is the document's, not the model's
    assert "This paragraph carries" in out[0]["rationale"]  # the section's own OPENING words as evidence
    assert all("llama3.2" in p["source"] for p in out)


def test_gates_mirror_the_detector(tmp_path, monkeypatch):
    import ai
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "suggest_fix", lambda *a, **k: {"suggestion": "X", "model": "m"})
    # Has heading styles → not this finding.
    styled = _docx(tmp_path, '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                             "<w:r><w:t>Title</w:t></w:r></w:p>"
                             + "".join(_P.format(_LONG) for _ in range(20)))
    assert proposals.propose_section_headings(styled, ".docx") == []
    # Short memo → below the detector's paragraph floor.
    short = _docx((tmp_path / "s").mkdir() or tmp_path / "s", "".join(_P.format(_LONG) for _ in range(4)))
    assert proposals.propose_section_headings(short, ".docx") == []


def test_ai_off_degrades_to_plain_review(tmp_path):
    assert proposals.propose_section_headings(_headingless(tmp_path), ".docx",
                                              ai_enabled=False) == []


def test_wiring_and_capability():
    root = Path(__file__).resolve().parent.parent
    src = (root / "api" / "handlers.py").read_text()
    assert "propose_section_headings" in src and '"2.4.10", "Section Headings"' in src
    import remediation_capability as cap
    assert cap.mode_for("docx", "2.4.10") == cap.ASSISTED
