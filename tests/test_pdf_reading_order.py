"""`pdf.reading-order` cannot fire, and the obvious one-word fix would be worse than the bug.

WHAT THIS FILE IS FOR. `acp-core-17` claims 1.3.2 on .pdf, and the comment above that table says
its per-format asymmetries are "the engine's real coverage, not an editorial choice". For .pdf
that is not true today: the only detector that could emit 1.3.2 on a PDF is
`analysers.rules.pdf.reading_order.ReadingOrderRule`, and it returns nothing on every input,
including a document whose content stream is written in exactly reverse visual order.

That is invisible from reading the code, which is why it survived. The rule looks right — it
computes a divergence, compares it to a threshold, builds a well-formed issue. It just measures
a list that has already been sorted into the order it is checking for.

WHY THE RULE IS DEAD. `page.extract_words(use_text_flow=False)` PRESORTS words by (top, x0).
`_compute_divergence` then sorts that same list by (top, x0) and counts positions that moved.
Sorting an already-sorted list moves nothing, so the divergence is 0.0 for every document ever
scanned and the threshold is never reached. The flag means "ignore the PDF's own character flow",
which is precisely the signal the rule exists to look at.

WHY THE ONE-WORD FIX IS NOT THE FIX. `use_text_flow=True` does make the rule fire — it is also
what the rule's own docstring describes. But `_compute_divergence` compares the stream against a
naive (top, x0) sort, and that is not the visual reading order of a multi-column page: column
one's second line sorts above column two's first. Measured on well-formed fixtures below, THREE
classes of correct document blow past the 25% threshold:

    two-column layout                       78%
    footnote drawn before the body         100%
    TAGGED, order defined by the tree      100%

all false positives, on documents with nothing wrong with them. Flipping the flag alone would
take a detector that reports nothing and turn it into one that reports confidently on correct
documents, which is the worse of the two failures: a silent detector understates, and a wrong
one gets acted on.

The third is the sharpest, because it is worst exactly where it should be best: a tagged PDF is
one that has BEEN through an accessibility workflow, its reading order is defined by the
structure tree, and the content stream it is measured against does not decide what a reader
gets. The fix for that one is also already written, in the AI path for this same criterion —
`remediate_pdf._propose_reading_order` returns early on `/StructTreeRoot`. The detector never
asks.

So 1.3.2 on .pdf needs a tagged gate AND column-aware visual ordering before it can mean
anything, and until then the corpus has no fixture for it — a ground-truth pair asserts that a
detector fires, and this one cannot. These tests pin the measurement so the next person to find the dead rule finds the
reason it was left alone rather than re-deriving the one-word change and shipping it.

See also the 1.4.3-on-PDF story in CLAUDE.md: a fixer that assumed a white page rewrote compliant
dark-theme PDFs from 21:1 to 3.66:1, unattended. Detectors that are confidently wrong cost more
than detectors that are quiet.
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
    _DIVERGENCE_THRESHOLD,
    ReadingOrderRule,
    _compute_divergence,
)

W, H = 500, 400


def _canvas(path: Path):
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(HexColor("#111111"))
    return c


def _lines_in_stream_order(path: Path, order: list[int]) -> None:
    """Eight lines laid out top-to-bottom, DRAWN in `order`. `order == range(8)` is a correct
    document; `reversed` is the worst reading-order defect a PDF can have."""
    c = _canvas(path)
    c.setFont("Helvetica", 12)
    placed = {i: (40, H - 40 - i * 30, f"Line{i} alpha bravo charlie") for i in range(8)}
    for i in order:
        x, y, text = placed[i]
        c.drawString(x, y, text)
    c.save()


def _divergences(path: Path) -> tuple[float, float]:
    """(what the rule measures today, what it would measure with use_text_flow=True)."""
    with pdfplumber.open(str(path)) as pl:
        page = pl.pages[0]
        return (_compute_divergence(page.extract_words(use_text_flow=False)),
                _compute_divergence(page.extract_words(use_text_flow=True)))


def _fires(path: Path) -> bool:
    with pikepdf.open(str(path)) as pk, pdfplumber.open(str(path)) as pl:
        return bool(ReadingOrderRule().check(pk, pl))


# ── the rule is dead ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,order", [
    ("correct", list(range(8))),
    ("fully reversed", list(reversed(range(8)))),
    ("scrambled", [7, 0, 6, 1, 5, 2, 4, 3]),
])
def test_the_rule_reports_nothing_however_scrambled_the_content_stream_is(tmp_path, label, order):
    """The finding, stated so it cannot be mistaken for a passing document. A fully reversed
    stream is the unambiguous 1.3.2 failure — every screen reader reads the page bottom-up — and
    the rule returns an empty list for it.

    If this test starts FAILING, the rule has been fixed. That is good news and the right
    response is to delete this file and write the corpus pair it was blocking; do not "fix" the
    test to keep it green."""
    pdf = tmp_path / f"{label.replace(' ', '-')}.pdf"
    _lines_in_stream_order(pdf, order)
    assert not _fires(pdf), (
        f"pdf.reading-order fired on the {label} stream — the rule is no longer dead. Delete "
        f"this file and add the 1.3.2 .pdf corpus pair it was blocking")


def test_the_divergence_is_exactly_zero_because_the_list_is_pre_sorted(tmp_path):
    """The mechanism, not just the symptom — so the next reader does not conclude the threshold
    is merely too high and lower it. The number is 0.0, not 0.2: no amount of threshold tuning
    reaches it, because nothing is ever measured as out of order."""
    pdf = tmp_path / "reversed.pdf"
    _lines_in_stream_order(pdf, list(reversed(range(8))))
    today, with_flow = _divergences(pdf)
    assert today == 0.0, (
        "the presorted list now yields non-zero divergence — re-derive this file's claim")
    assert with_flow > _DIVERGENCE_THRESHOLD, (
        "the signal is not in the text-flow ordering either; this file's diagnosis is wrong")


def test_the_word_list_the_rule_reads_is_already_in_visual_order(tmp_path):
    """Named directly rather than left as an inference from the zero above: with
    use_text_flow=False the first word pdfplumber returns is the TOP line even when the stream
    drew it last. That single fact is the whole bug."""
    pdf = tmp_path / "reversed.pdf"
    _lines_in_stream_order(pdf, list(reversed(range(8))))
    with pdfplumber.open(str(pdf)) as pl:
        page = pl.pages[0]
        presorted = page.extract_words(use_text_flow=False)
        flowed = page.extract_words(use_text_flow=True)
    assert presorted[0]["text"] == "Line0", "presorted order is no longer visual order"
    assert flowed[0]["text"] == "Line7", "text-flow order no longer follows the content stream"


# ── and the one-word fix would be worse ──────────────────────────────────────────

def _two_column(path: Path) -> None:
    """Correct: column one is drawn in full, then column two. Naive (top, x0) sorting interleaves
    them, so the stream looks 'out of order' to the current divergence maths."""
    c = _canvas(path)
    c.setFont("Helvetica", 11)
    for i in range(9):
        c.drawString(40, H - 40 - i * 25, f"Left column line {i} words")
    for i in range(9):
        c.drawString(270, H - 40 - i * 25, f"Right column line {i} words")
    c.save()


def _footnote_first(path: Path) -> None:
    """Also correct: a footnote emitted before the body that references it, which real layout
    engines do routinely."""
    c = _canvas(path)
    c.setFont("Helvetica", 8)
    c.drawString(40, 30, "1. See appendix B for the full methodology and sampling frame.")
    c.setFont("Helvetica", 11)
    for i in range(8):
        c.drawString(40, H - 45 - i * 25, f"Body line {i} of the main narrative text")
    c.save()


def _single_column(path: Path) -> None:
    c = _canvas(path)
    c.setFont("Helvetica", 11)
    for i in range(12):
        c.drawString(40, H - 40 - i * 25, f"Paragraph line {i} with several ordinary words here")
    c.save()


@pytest.mark.parametrize("name,build", [("two column", _two_column),
                                        ("footnote drawn first", _footnote_first)])
def test_flipping_the_flag_alone_would_fire_on_well_formed_documents(tmp_path, name, build):
    """The reason this is not a one-word fix, measured rather than asserted. Both documents are
    correct — a reader of either gets the right sequence — and both blow past the threshold once
    the divergence is computed against the content stream, because the comparison order is a flat
    (top, x0) sort that does not understand columns.

    This is the test to look at before changing `use_text_flow`. It does not forbid the change; it
    says what else has to change with it."""
    pdf = tmp_path / (name.replace(" ", "-") + ".pdf")
    build(pdf)
    _today, with_flow = _divergences(pdf)
    assert with_flow >= _DIVERGENCE_THRESHOLD, (
        f"{name} no longer false-positives under use_text_flow=True — if _compute_divergence "
        f"became column-aware, this file's objection is answered and 1.3.2 on .pdf can have a "
        f"real corpus pair")


# ── and a TAGGED document is a third false positive, with a gate already written next door ──

def _tagged(src: Path, dst: Path, elements: int = 8) -> None:
    """Turn a PDF into a TAGGED one: give it a StructTreeRoot with a paragraph element per line.

    This is what "reading order is defined" MEANS for a PDF. A tagged document's order comes from
    the structure tree, which is what assistive technology walks; the order things happen to be
    drawn in the content stream is then irrelevant to a reader, and routinely differs from it —
    that is the normal output of every tagging workflow, not a defect.
    """
    with pikepdf.open(str(src)) as pdf:
        page = pdf.pages[0]
        root = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructTreeRoot, K=pikepdf.Array([])))
        root.K = pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, P=root, Pg=page.obj))
            for _ in range(elements)])
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.save(str(dst))


def test_the_rule_never_asks_whether_the_document_is_tagged(tmp_path):
    """THE THIRD FALSE POSITIVE, and the one with a fix already written twelve files away.

    A tagged PDF whose structure tree defines a correct reading order still measures 100%
    divergence off its content stream, because the rule reads the stream and never looks at the
    tree. So flipping the flag would flag correctly-tagged documents — the documents that are
    MOST likely to have been through an accessibility workflow — at the top of the scale.

    The gate is not hypothetical or hard: `remediate_pdf._propose_reading_order`, the AI path for
    this same criterion, opens with

        if "/StructTreeRoot" in pdf.Root:
            return  # tagged -> reading order comes from the structure tree, not a guess

    The detector has no equivalent. Two code paths answering one question, one of which knows
    something the other does not — so this is recorded as a specific, small prerequisite rather
    than left inside the general "the maths is wrong" objection.
    """
    scrambled = tmp_path / "scrambled.pdf"
    _lines_in_stream_order(scrambled, list(reversed(range(8))))
    tagged = tmp_path / "scrambled-tagged.pdf"
    _tagged(scrambled, tagged)

    with pikepdf.open(str(tagged)) as pk:
        assert "/StructTreeRoot" in pk.Root, "the fixture must actually be tagged to be a fixture"

    today, with_flow = _divergences(tagged)
    assert today == 0.0, "dead today, tagged or not"
    assert with_flow >= _DIVERGENCE_THRESHOLD, (
        "a tagged document no longer false-positives under text flow — if the rule learned to "
        "read the structure tree, say so here and in the module docstring")
    assert not _fires(tagged), "the rule reports nothing today, which is the whole point"


def test_a_correctly_tagged_and_correctly_streamed_document_is_clean(tmp_path):
    """The control for the case above. Without it, "tagged scores 100%" is consistent with
    "tagging itself breaks the measurement", which would be a different bug and a different fix."""
    correct = tmp_path / "correct.pdf"
    _lines_in_stream_order(correct, list(range(8)))
    tagged = tmp_path / "correct-tagged.pdf"
    _tagged(correct, tagged)

    today, with_flow = _divergences(tagged)
    assert today == 0.0
    assert with_flow < _DIVERGENCE_THRESHOLD, (
        "tagging alone moved the divergence — the fixture, not the document, is what differs "
        "between this test and the one above")


def test_a_single_column_document_is_clean_either_way(tmp_path):
    """The control. Without it, the two assertions above would be consistent with 'the text-flow
    reading is simply always high', which would make them evidence of nothing."""
    pdf = tmp_path / "single-column.pdf"
    _single_column(pdf)
    today, with_flow = _divergences(pdf)
    assert today == 0.0
    assert with_flow < _DIVERGENCE_THRESHOLD, (
        "even a single-column document diverges under text flow — the divergence maths is more "
        "broken than this file claims")


# ── so the preset's claim about (1.3.2, .pdf) is not currently earned ────────────

def test_the_preset_still_claims_1_3_2_on_pdf_and_that_is_recorded_here():
    """Deliberately NOT a failure. Removing (1.3.2, .pdf) from `acp-core-17` would drop the
    reporting denominator from 62 pairs to 61 and change the headline coverage number, which is a
    product decision rather than a test's to make — the denominator was chosen explicitly
    (2026-08-30) and the alternative is to fix the detector and keep the pair.

    What this asserts is that the claim is still there, so that if someone acts on this file by
    editing the preset instead of the detector, that shows up as this test failing and gets a
    sentence written about which of the two was chosen."""
    sys.path.insert(0, str(ROOT / "api"))
    import assessment_policy as ap
    assert "pdf" in ap.SCOPE_PRESETS["acp-core-17"]["1.3.2"], (
        "(1.3.2, pdf) left acp-core-17 — if that was the chosen answer to the dead detector, say "
        "so here and update the coverage denominator from 62 in gen_fixture_coverage.py")
