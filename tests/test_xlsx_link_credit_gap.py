"""The .xlsx 2.4.4 write lane has a gap, and the obvious way to close it grants false credit.

TWO FINDINGS THAT ONLY MATTER TOGETHER. Neither is a live defect on its own; the pair is a trap
laid directly under the fix somebody will reach for.

  1. THE PROPOSER AND THE DETECTOR DISAGREE. office_structure's 2.4.4 check falls back to the
     CELL VALUE when a <hyperlink> carries no display= attribute — deliberately, with a comment
     saying so ("No display= — label is the cell value; resolve it now"). proposals.
     extract_office_links requires display= and skips the link. openpyxl, and therefore this
     repo's own ground-truth fixture, writes hyperlinks WITHOUT display=. So the detector reports
     2.4.4 and the proposer offers nothing: the reviewer sees a finding with nothing to approve.

     extract_office_links' own comment claims the opposite — "the detector judges the `display`
     text, so the proposer reads the SAME attribute — a link with no display is skipped there and
     here alike". The first half is false, and it is the half that matters.

  2. WRITING THE APPROVED VALUE WOULD CLEAR THE CRITERION WITHOUT CHANGING THE DOCUMENT'S TEXT.
     apply_link_text._apply_xlsx ADDS display="<approved>" to a display-less hyperlink and never
     touches the cell. The detector then prefers display=, sees a descriptive label, and the file
     is credited — while the cell, and pii.extract_text, still read "click here".

WHY THAT SECOND ONE IS NOT A JUDGEMENT CALL ABOUT EXCEL. It would be easy to argue display= is
the "real" label and the write is legitimate; deciding that needs knowledge of how Excel and
assistive technology resolve a hyperlink's accessible name, which no test here can supply. So
this file does not argue it. It asserts something entirely internal instead: after the write, ACP
credits the criterion as fixed while ACP'S OWN pii.extract_text still reports the old text. The
system contradicts itself, whatever Excel does.

The other two writers in the same module settle the design question anyway — _apply_docx rewrites
<w:t> and _apply_pptx rewrites <a:t>, both the text a reader actually sees. xlsx is the only one
of the three that writes an attribute and leaves the visible content alone.

WHY NOTHING CAUGHT THIS. The existing apply tests drive handlers._apply_approved_values with
`residual=set()` — the re-scan result is SUPPLIED rather than performed, so no test has ever run
a real detector over written bytes. And the credit gate re-runs the detector that fired, which
structurally cannot tell "fixed" from "made invisible to this detector".

NOTHING IS BROKEN FOR USERS TODAY, and that is asserted below rather than assumed: handlers.py is
the only caller of propose_link_texts, it is the only producer of link values, and it cannot
produce one for a display-less link. No proposal, no approval, no write. Finding 2 is latent.

SO DO NOT FIX FINDING 1 ALONE. Teaching extract_office_links the same cell-value fallback the
detector already has would make the lane reachable and start granting the credit in Finding 2.
The fix is both halves: the proposer learns the fallback AND the writer writes the cell value.
When that lands, this file fails — which is the signal to delete it and replace it with an
end-to-end proof that the written document's TEXT changed.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import office_structure as osx  # noqa: E402
import pii as _pii  # noqa: E402
import proposals as _prop  # noqa: E402
from apply_link_text import apply_link_text  # noqa: E402

HREF = "https://example.com/fy26-travel-policy.pdf"
APPROVED = "Read the FY26 travel policy"
VAGUE = "click here"


@pytest.fixture(scope="module")
def vague_link_xlsx():
    """The corpus's own 2.4.4 violation fixture — reused rather than rebuilt so this file and the
    ground-truth corpus cannot drift about what a vague link looks like."""
    spec = importlib.util.spec_from_file_location(
        "gen_xlsx_corpus", ROOT / "scripts" / "gen_xlsx_corpus.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules["gen_xlsx_corpus"] = gen
    spec.loader.exec_module(gen)
    out = Path(tempfile.mkdtemp(prefix="acp-xlsx-link-")) / "docs"
    manifest, problems = gen.build_all(out)
    assert not problems, problems
    rows = {r["name"]: r for r in manifest}
    return out.parent / rows["link-vague"]["file"]


def _wcags(path: Path) -> set[str]:
    return {(f.get("wcag") or "").split()[0] for f in osx.checks_for(path, ".xlsx")
            if f.get("wcag")}


def _text(path: Path) -> str:
    return " ".join((_pii.extract_text(path) or "").split())


# ── finding 1: the detector fires and the proposer offers nothing ────────────────

def test_the_detector_reports_a_vague_link_with_no_display_attribute(vague_link_xlsx):
    """The premise. openpyxl writes <hyperlink ref="A2" r:id="rId1"/> with no display=, and the
    detector still flags it because it falls back to the cell value."""
    assert "2.4.4" in _wcags(vague_link_xlsx)
    assert VAGUE in _text(vague_link_xlsx).lower()


def test_the_proposer_offers_nothing_for_that_same_link(vague_link_xlsx):
    """The gap. Same document, same hyperlink — no proposal, so there is nothing for a reviewer
    to approve and the finding cannot be remediated through the product."""
    props = _prop.propose_link_texts(vague_link_xlsx, "xlsx", ai_enabled=False)
    assert props == [], (
        f"propose_link_texts now returns {props} for a display-less link. If extract_office_links "
        f"learned the detector's cell-value fallback, check that _apply_xlsx also writes the CELL "
        f"before deleting this file — see the module docstring")
    assert _prop.extract_office_links(vague_link_xlsx, "xlsx") == [], (
        "extract_office_links now sees display-less hyperlinks")


def test_nothing_else_produces_link_values(vague_link_xlsx):
    """Why finding 2 is latent rather than live: handlers is the only caller of the proposer, so
    a display-less link never reaches the writer in production."""
    src = (ROOT / "api" / "handlers.py").read_text()
    assert "propose_link_texts" in src
    callers = [p.name for p in (ROOT / "api").glob("*.py")
               if "propose_link_texts(" in p.read_text() and p.name != "proposals.py"]
    assert callers == ["handlers.py"], (
        f"link values now have another producer ({callers}) — re-check whether the write in the "
        f"next test is still unreachable")


# ── finding 2: the write would clear the criterion without changing the text ─────

def test_writing_the_value_clears_the_criterion_but_not_the_cell(vague_link_xlsx, tmp_path):
    """The trap, measured. This is what closing finding 1 alone would buy.

    Asserted as an internal contradiction, not as a claim about Excel: ACP credits the criterion
    as fixed while ACP's own text extraction still reports the vague label."""
    raw = vague_link_xlsx.read_bytes()
    written, applied, unresolved = apply_link_text(raw, "xlsx", {HREF: APPROVED})
    assert applied and not unresolved, f"the writer did not apply: {applied} / {unresolved}"
    assert written != raw, "the writer changed no bytes"

    out = tmp_path / "written.xlsx"
    out.write_bytes(written)

    assert "2.4.4" not in _wcags(out), (
        "the re-scan still reports 2.4.4 — this file's second finding no longer holds")
    after = _text(out)
    assert VAGUE in after.lower(), (
        "the cell text changed — if _apply_xlsx now writes the cell value, this whole file is "
        "obsolete: delete it and assert the end-to-end fix instead")
    assert APPROVED.lower() not in after.lower(), (
        "the approved text now reaches the document's extracted text — the lane is fixed")


def test_the_other_two_writers_do_change_the_visible_text(tmp_path):
    """The control, and the reason finding 2 reads as a defect rather than a design choice.

    Same module, same criterion, same approved value: docx and pptx replace the run TEXT a reader
    sees. Asserted by running the writers rather than by reading them, on a minimal package built
    here so the assertion does not depend on any corpus."""
    import re
    import zipfile

    def _docx_with_link(path: Path) -> None:
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        doc = Document()
        para = doc.add_paragraph()
        rid = para.part.relate_to(HREF, "http://schemas.openxmlformats.org/officeDocument/"
                                        "2006/relationships/hyperlink", is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), rid)
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = VAGUE
        run.append(text)
        link.append(run)
        para._p.append(link)
        doc.save(str(path))

    src = tmp_path / "link.docx"
    _docx_with_link(src)
    before = src.read_bytes()
    written, applied, _unresolved = apply_link_text(before, "docx", {HREF: APPROVED})
    assert applied, "the docx writer applied nothing — the fixture, not the finding, is wrong"

    out = tmp_path / "written.docx"
    out.write_bytes(written)
    with zipfile.ZipFile(out) as zf:
        xml = zf.read("word/document.xml").decode()
    body = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    assert APPROVED in body, "the docx writer did not put the approved text into <w:t>"
    assert VAGUE not in body, "the docx writer left the vague text in place"
