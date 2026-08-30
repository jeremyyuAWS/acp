"""The .xlsx 2.4.4 remediation lane — two gaps, now CLOSED, kept as the record of what they were.

STATUS: both gaps below are fixed. The assertions here were written as the behaviour ACP should
have and carried `xfail(strict=True)` until it did; when the fix landed they XPASSed, and per
their own instructions the markers were deleted and the assertions kept. They are ordinary
regression tests now, and this header is history rather than a warning — worth keeping because
the SHAPE of the defect (two halves of one feature disagreeing, each defensible alone) is the
thing likely to recur.

One test was deleted rather than converted: `test_acp_credits_the_criterion_while_its_own
_extraction_disagrees` asserted the internal inconsistency as evidence, and its own docstring said
to remove it once the positive assertion in `test_the_written_file_carries_the_approved_text`
could stand in its place. It can, and it does.

The end-to-end proof of the fixed lane — shared-string integrity, formulas, styles, refusals —
lives in tests/test_remediation_verified_xlsx_link.py.

────────────────────────────────────────────────────────────────────────────────
GAP 1 — EXISTING USER-FACING LIMITATION (live until fixed; never latent)

A reviewer looking at a spreadsheet whose vague hyperlink carries no display= attribute sees a
2.4.4 finding and is offered nothing to approve. The finding is real, the lane is declared in
handlers._LINK_SCS_BY_EXT, and the criterion cannot be cleared through the product. That is a
limitation users hit now, on files openpyxl and other generators produce routinely.

The cause is a disagreement between two halves of the same feature. office_structure's 2.4.4 check
falls back to the CELL VALUE when a <hyperlink> carries no display= — deliberately, with a comment
saying so ("No display= — label is the cell value; resolve it now"). proposals.extract_office_links
requires display= and skips the link. Its own comment claims the opposite — "the detector judges
the `display` text, so the proposer reads the SAME attribute — a link with no display is skipped
there and here alike". The first half is false, and it is the half that matters.

────────────────────────────────────────────────────────────────────────────────
GAP 2 — SUSPECTED, LATENT, AND NOT PROVEN TO HARM ANYONE

If gap 1 were closed on its own, the write that followed would be apply_link_text._apply_xlsx,
which ADDS display="<approved>" and never touches the cell. The detector then prefers display=,
sees a descriptive label, and the criterion clears.

WHAT WAS ESTABLISHED: after that write, ACP credited 2.4.4 as resolved while ACP's own
pii.extract_text still reported the original label — an internal inconsistency between what this
system credited and what this system read.

WHAT WAS NEVER ESTABLISHED, and is still not claimed: whether a user or a screen reader would have
encountered the vague label. That depends on how Excel and assistive technology resolve a
hyperlink's accessible name from display= versus the cell value, which nothing available here can
determine. The fix sidesteps the question rather than answering it — the writer now moves the CELL
VALUE, which is the text a sighted reader sees either way, and keeps display= in step with it.

It was latent because it was unreachable: handlers.py is the only producer of link values and
could not produce one for a display-less link, so no approval and no write occurred. Closing gap 1
made it reachable, which is exactly why the two had to be fixed together. The producer count is
still asserted below, now as a guard: a second producer would change this reasoning.

────────────────────────────────────────────────────────────────────────────────
WHY BOTH HALVES ARE ONE CHANGE

Teaching extract_office_links the fallback the detector already has made the lane reachable and
would have taken the suspected path with it. So the fix was extraction, proposal, writer and
verification together: the proposer learned the fallback, the writer now writes the CELL VALUE (as
_apply_docx and _apply_pptx already write <w:t> and <a:t> — asserted below as the control), the
saved file is re-opened through the real path, and hyperlink targets, formatting, formulas and
shared-string integrity are shown intact.

WHY NOTHING CAUGHT THIS. The existing apply tests drive handlers._apply_approved_values with
residual=set() — the re-scan result is supplied rather than performed, so no test has run a real
detector over written bytes. And the credit gate re-runs the detector that fired, which
structurally cannot separate "fixed" from "no longer visible to this detector".
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import zipfile
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


# ── what already works ───────────────────────────────────────────────────────────

def test_the_detector_reports_a_vague_link_with_no_display_attribute(vague_link_xlsx):
    """Working as intended, and the premise for everything below. openpyxl writes
    <hyperlink ref="A2" r:id="rId1"/> with no display=, and the detector still flags it because it
    falls back to the cell value."""
    assert "2.4.4" in _wcags(vague_link_xlsx)
    assert VAGUE in _text(vague_link_xlsx).lower()


def test_the_docx_writer_changes_the_text_a_reader_sees(tmp_path):
    """The control, and the reason gap 2 reads as a defect rather than a design choice: the same
    module, for the same criterion, writes the visible run text on the other two formats.

    Asserted by RUNNING the docx writer on a package built here, so it depends on no corpus and on
    no reading of the source."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    src = tmp_path / "link.docx"
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
    doc.save(str(src))

    written, applied, _unresolved = apply_link_text(src.read_bytes(), "docx", {HREF: APPROVED})
    assert applied, "the docx writer applied nothing — the fixture, not the finding, is wrong"
    out = tmp_path / "written.docx"
    out.write_bytes(written)
    with zipfile.ZipFile(out) as zf:
        xml = zf.read("word/document.xml").decode()
    body = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    assert APPROVED in body, "the docx writer did not put the approved text into <w:t>"
    assert VAGUE not in body, "the docx writer left the vague text in place"


# ── gap 1: a live limitation, stated as the behaviour we want ────────────────────

def test_a_vague_link_gets_a_proposal_a_reviewer_can_act_on(vague_link_xlsx):
    """What should happen: a document the detector flags for 2.4.4 offers the reviewer something
    to approve. Today it does not, for any spreadsheet whose hyperlink has no display=.

    Closing this alone is not the fix — see the module docstring and gap 2."""
    props = _prop.propose_link_texts(vague_link_xlsx, "xlsx", ai_enabled=False)
    assert props, (
        "no proposal for a link the detector flagged — the finding cannot be remediated")
    assert any((p.get("locator") or "") == HREF for p in props), (
        f"proposals exist but none is keyed by the link's href: {[p.get('locator') for p in props]}")


# ── gap 2: suspected, latent, and unreachable today ──────────────────────────────

def test_the_write_is_unreachable_because_nothing_produces_the_value(vague_link_xlsx):
    """Why gap 2 is latent rather than live. handlers.py is the only caller of the proposer, and
    the proposer yields nothing here, so no approval and no write occur.

    This is a blast-radius fact, not a defect: if another producer appears, gap 2 stops being
    latent and this test is the place that says so."""
    callers = sorted(p.name for p in (ROOT / "api").glob("*.py")
                     if "propose_link_texts(" in p.read_text() and p.name != "proposals.py")
    assert callers == ["handlers.py"], (
        f"link values now have another producer ({callers}) — re-assess whether the suspected "
        f"path below is still unreachable")


def test_the_written_file_carries_the_approved_text(vague_link_xlsx, tmp_path):
    """What should happen: after an approved value is written, the document ACP reads back
    contains the approved text and no longer contains the vague one.

    A fix for this must also keep the hyperlink target, cell formatting, formulas and
    shared-string integrity intact, and must verify the saved file through the real path — this
    assertion is the floor, not the whole bar."""
    written, applied, unresolved = apply_link_text(
        vague_link_xlsx.read_bytes(), "xlsx", {HREF: APPROVED})
    assert applied and not unresolved, f"the writer did not apply: {applied} / {unresolved}"
    out = tmp_path / "written.xlsx"
    out.write_bytes(written)

    after = _text(out)
    assert APPROVED.lower() in after.lower(), (
        "the approved text is absent from the written document's extracted text")
    assert VAGUE not in after.lower(), "the vague label survives in the written document"
