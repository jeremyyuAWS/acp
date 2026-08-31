"""Acceptance tests for `pdf.reading-order` as a BOUNDED capability.

WHAT CHANGED, and why this file was rewritten rather than extended. It used to document a rule
that could not fire: `extract_words(use_text_flow=False)` presorted words by (top, x0) and
`_compute_divergence` sorted that same list by (top, x0), so the divergence was 0.0 on every
input including a fully reversed content stream. Those tests asserted the deadness, and measured
that the one-word fix (`use_text_flow=True`) would be WORSE — three ordinary correct layouts
scored 78%, 100% and 100% against a 25% threshold.

The rule now reports on one shape of page and abstains on the rest, so the assertions here are
the boundary rather than the deadness. Each abstention corresponds to one of those measured
false positives, and each is tested positively — an abstention nobody exercises is a comment.

THE DISTINCTION THIS FILE EXISTS TO KEEP: ABSTAINING IS NOT PASSING. The rule returns no issue
for a tagged document, a two-column page and a footnote page alike, and in none of those cases
has it formed the opinion that the order is correct. That is why (1.3.2, pdf) stays visibly
uncovered in the capability report: a criterion nothing assesses must not read as one that
passed. The last test pins that.

TAGGED DOCUMENTS GET THREE CASES, NOT ONE. Well-formed, malformed, and correctly-formed-but-
mis-ordered. All three abstain, and that is the point: the rule cannot tell them apart, so
finding /StructTreeRoot must never stand in for "the order is right". A version that abstained
only on the well-formed tree — or worse, treated the tag's presence as a pass — would look
identical on the first case.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_ENGINE = ROOT / "engine" / "pdf-analyser"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

pdfplumber = pytest.importorskip("pdfplumber")
pikepdf = pytest.importorskip("pikepdf")
_rl = pytest.importorskip("reportlab.pdfgen")

from analysers.rules.pdf.reading_order import (  # noqa: E402
    _INVERSION_THRESHOLD,
    ReadingOrderRule,
    _has_out_of_flow,
    _inversion_ratio,
    _is_tagged,
    _stream_lines,
    _vertical_gutter,
)

W, H = 500, 400


# ── fixtures: real PDFs, built to trip one thing each ────────────────────────────
def _canvas(path: Path):
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(HexColor("#111111"))
    return c


def _single_column(path: Path, order: list[int]) -> None:
    """Eight lines laid out top-to-bottom, DRAWN in `order`."""
    c = _canvas(path)
    c.setFont("Helvetica", 12)
    placed = {i: (40, H - 40 - i * 30, f"Line{i} alpha bravo charlie") for i in range(8)}
    for i in order:
        x, y, text = placed[i]
        c.drawString(x, y, text)
    c.save()


def _two_column(path: Path) -> None:
    """Correct: column one drawn in full, then column two."""
    c = _canvas(path)
    c.setFont("Helvetica", 11)
    for i in range(9):
        c.drawString(40, H - 40 - i * 25, f"Left column line {i} words")
    for i in range(9):
        c.drawString(270, H - 40 - i * 25, f"Right column line {i} words")
    c.save()


def _footnote_first(path: Path) -> None:
    """Also correct: a footnote emitted before the body that references it."""
    c = _canvas(path)
    c.setFont("Helvetica", 8)
    c.drawString(40, 30, "1. See appendix B for the full methodology and sampling frame.")
    c.setFont("Helvetica", 11)
    for i in range(8):
        c.drawString(40, H - 45 - i * 25, f"Body line {i} of the main narrative text")
    c.save()


def _tag(src: Path, dst: Path, *, kind: str = "well_formed") -> None:
    """Add a structure tree. `kind` picks how good it is — all three must abstain alike."""
    with pikepdf.open(str(src)) as pdf:
        page = pdf.pages[0]
        root = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructTreeRoot, K=pikepdf.Array([])))
        if kind == "malformed":
            # A tree that exists but says nothing: no kids, no page links. Real files carry
            # trees this broken, and the rule must not read the tag as a guarantee.
            root.K = pikepdf.Array([])
        else:
            kids = [pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, P=root, Pg=page.obj))
                for _ in range(8)]
            if kind == "misordered":
                kids.reverse()      # a well-formed tree that states the WRONG order
            root.K = pikepdf.Array(kids)
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.save(str(dst))


def _fires(path: Path) -> list:
    with pikepdf.open(str(path)) as pk, pdfplumber.open(str(path)) as pl:
        return ReadingOrderRule().check(pk, pl)


def _ratio(path: Path) -> float:
    with pdfplumber.open(str(path)) as pl:
        return _inversion_ratio(_stream_lines(pl.pages[0]))


# ── 1. the capability: it reports the defect it is for ───────────────────────────
def test_a_scrambled_untagged_single_column_page_is_reported(tmp_path):
    """THE CAPABILITY. The case the old rule could not detect on any input: an untagged page
    whose content stream is the exact reverse of its layout. A screen reader follows the stream,
    so this reads the page backwards."""
    pdf = tmp_path / "reversed.pdf"
    _single_column(pdf, list(reversed(range(8))))

    issues = _fires(pdf)
    assert len(issues) == 1, f"expected one finding, got {issues}"
    assert issues[0].rule_id == "pdf.reading-order"
    assert issues[0].location.page_number == 1
    assert _ratio(pdf) == 1.0, "a fully reversed stream should measure 1.0"


def test_a_correctly_ordered_page_is_silent(tmp_path):
    """The control that makes the test above mean something. Same fixture, correct order."""
    pdf = tmp_path / "correct.pdf"
    _single_column(pdf, list(range(8)))
    assert _fires(pdf) == []
    assert _ratio(pdf) == 0.0


@pytest.mark.parametrize("label,order", [
    ("swap the middle pair", [0, 1, 2, 4, 3, 5, 6, 7]),
    ("one line late", [0, 2, 3, 4, 5, 6, 7, 1]),
])
def test_a_small_permutation_is_not_reported(tmp_path, label, order):
    """The threshold, exercised rather than asserted in a comment. A slight departure is more
    often a layout artefact this rule has not learned than a real defect, so only a gross
    permutation is reported. Without this, `_INVERSION_THRESHOLD` could be 0 and every test
    above would still pass."""
    pdf = tmp_path / (label.replace(" ", "-") + ".pdf")
    _single_column(pdf, order)
    assert _ratio(pdf) < _INVERSION_THRESHOLD, f"{label}: fixture is grosser than intended"
    assert _fires(pdf) == [], f"{label} was reported, but is below the threshold"


# ── 2. the boundary: the three measured false positives now abstain ──────────────
def test_a_two_column_page_abstains(tmp_path):
    """78% under the naive comparison, and correct. The gutter is what the rule sees."""
    pdf = tmp_path / "two-column.pdf"
    _two_column(pdf)

    with pdfplumber.open(str(pdf)) as pl:
        page = pl.pages[0]
        gutter = _vertical_gutter(_stream_lines(page), page.width)
    assert gutter is not None, "the fixture must actually present a gutter to be a fixture"
    assert _fires(pdf) == [], "a correct two-column layout must not be reported"


def test_a_footnote_drawn_before_the_body_abstains(tmp_path):
    """100% under the naive comparison, and the normal output of every layout engine."""
    pdf = tmp_path / "footnote.pdf"
    _footnote_first(pdf)

    with pdfplumber.open(str(pdf)) as pl:
        assert _has_out_of_flow(_stream_lines(pl.pages[0])), (
            "the fixture must actually present a smaller out-of-flow line")
    assert _fires(pdf) == [], "a footnote drawn before its body must not be reported"


def test_too_few_lines_abstains(tmp_path):
    """Nothing to draw a conclusion from."""
    pdf = tmp_path / "sparse.pdf"
    c = _canvas(pdf)
    c.setFont("Helvetica", 12)
    c.drawString(40, 200, "Only one line here")
    c.save()
    assert _fires(pdf) == []


# ── 3. tagged: three trees, one answer, and it is never "correct" ────────────────
@pytest.mark.parametrize("kind", ["well_formed", "malformed", "misordered"])
def test_every_tagged_document_abstains_however_good_its_tree(tmp_path, kind):
    """THE ASYMMETRY THAT MATTERS. All three trees produce the same silence, on a page whose
    content stream is fully reversed — so the silence cannot be coming from the stream looking
    fine. `misordered` is the sharp one: a well-formed tree that states the WRONG order abstains
    exactly like a right one, because this rule does not read the tree and must not pretend to.

    Finding /StructTreeRoot means "not assessable here", never "correctly ordered"."""
    scrambled = tmp_path / f"src-{kind}.pdf"
    _single_column(scrambled, list(reversed(range(8))))
    tagged = tmp_path / f"tagged-{kind}.pdf"
    _tag(scrambled, tagged, kind=kind)

    with pikepdf.open(str(tagged)) as pk:
        assert _is_tagged(pk), "the fixture must actually be tagged"
    assert _fires(tagged) == [], f"{kind}: a tagged document must not be assessed by this rule"
    # ...and the untagged twin IS reported, so the abstention is the tagging, nothing else.
    assert len(_fires(scrambled)) == 1, "the same bytes untagged must still be reported"


def test_an_unreadable_root_abstains_rather_than_assessing(tmp_path):
    """Ambiguity resolves to "do not assess", matching the rest of this repo's fail-closed
    posture. A rule that assessed whatever it could not classify would reintroduce exactly the
    confident-and-wrong behaviour it was rewritten to remove."""
    class _Broken:
        @property
        def Root(self):
            raise RuntimeError("cannot read the document catalog")

    assert _is_tagged(_Broken()) is True, "an unreadable catalog must read as 'do not assess'"


# ── 4. abstaining is not passing ─────────────────────────────────────────────────
def test_the_preset_still_claims_1_3_2_on_pdf_and_the_cell_stays_uncovered():
    """Deliberately NOT a failure, and the reason this file cannot end at "the rule works now".

    The rule reports one bounded shape of page. That is not the same as covering (1.3.2, pdf):
    tagged documents — every file that has been through an accessibility workflow — multi-column
    layouts, footnoted pages and tables are all still unassessed, and the rule is silent on each
    for reasons that have nothing to do with whether their order is right.

    So the pair stays claimed by the preset AND visibly uncovered in the capability report until
    a ground-truth corpus pair earns the narrower claim. If someone answers the dead detector by
    editing the preset instead, that shows up here."""
    sys.path.insert(0, str(ROOT / "api"))
    import assessment_policy as ap
    assert "pdf" in ap.SCOPE_PRESETS["acp-core-17"]["1.3.2"], (
        "(1.3.2, pdf) left acp-core-17 — if that was the chosen answer, say so here and update "
        "the coverage denominator from 62 in gen_fixture_coverage.py")
