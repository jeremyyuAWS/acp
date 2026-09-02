"""The WeasyPrint conformance report, checked as a screen reader would meet it.

WHAT THESE ASSERT, AND WHY NOT "IS THERE A STRUCTURE TREE". That question has a green answer for
a document with nothing in it — `api/report.py::_tag_pdf` bolts an EMPTY /StructTreeRoot onto
untagged ReportLab output and passes ACP's own `pdf.tagged` rule to this day. So every check here
walks the real tree and asks what a reader would actually get: a heading outline, header cells,
figures with alternatives, a link, the document's language and title.

THE ONE THAT MATTERS MOST IS THE CHARTS. Rendering the shipped template through WeasyPrint
unmodified passes veraPDF with zero failures and drops the charts from the tag tree entirely —
5 Figures under Chromium, 1 (the logo) under WeasyPrint, because WeasyPrint does not tag inline
<svg>. Conformant, and worse for the reader it is meant to serve. `test_every_chart_is_a_figure_
with_a_conclusion_stating_alt` is what stops that shape passing for compliance, and it is why the
charts are <img alt> + data table rather than inline SVG.

THE VALIDATOR IS THE OTHER HALF, not a substitute for these. veraPDF answers "is this PDF/UA-1";
it does not answer "did the two charts survive". The structural checks below run without veraPDF
installed, so a bare checkout still holds the renderer to its semantics.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("weasyprint")

from verapdf import NO_VERAPDF, VERAPDF_OK, validate  # noqa: E402

_FILES = [
    {"file": "a.pdf", "status": "done", "compliant": 1, "score": 90,
     "skipped_rules": 0, "issues": []},
    {"file": "b.docx", "status": "done", "compliant": 0, "score": 55, "skipped_rules": 0,
     "issues": [{"wcag": "SC_1_1_1", "severity": "CRITICAL"},
                {"wcag": "SC_2_4_2", "severity": "SERIOUS"}]},
    {"file": "c.xlsx", "status": "done", "compliant": 0, "score": 71, "skipped_rules": 2,
     "issues": [{"wcag": "SC_1_4_3", "severity": "MODERATE"}]},
]
_RUN = {"id": "selfcheck", "completed_at": "2026-08-04T00:00:00", "avg_score": 72,
        "files": 3, "certifiable": 1, "uncertain": 0, "error": 0}
_META = {"target": "WCAG 2.1 Level AA", "version": "3", "hash": "abc"}


def _build(tmp: Path, **over) -> Path:
    import report_weasy
    run = {**_RUN, **over.pop("run", {})}
    files = over.pop("files", _FILES)
    out = tmp / "report.pdf"
    out.write_bytes(report_weasy.build_weasy_report(run, files, _META))
    return out


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> Path:
    return _build(tmp_path_factory.mktemp("weasy"))


# ── walking the tree ─────────────────────────────────────────────────────────────────────────

def _walk(pdf) -> tuple[Counter, list[str], list[dict]]:
    """Every structure element, in reading order. Returns (tag counts, heading sequence, figures).

    Visited-set keyed on the PDF object id, NOT id(node): pikepdf returns a fresh wrapper on each
    access and CPython recycles those addresses, so an id()-keyed set produces false "already
    seen" hits and silently truncates the walk. An earlier version of this helper did exactly
    that and reported 2 headings and zero tables against a tree holding 5 headings, 2 tables,
    9 TH and 27 TD — a walker that under-reports makes every assertion below vacuous.
    """
    tags: Counter = Counter()
    headings: list[str] = []
    figures: list[dict] = []
    seen: set = set()

    def visit(node):
        if isinstance(node, pikepdf.Array):
            for kid in node:
                visit(kid)
            return
        if not isinstance(node, pikepdf.Dictionary):
            return
        try:
            oid = node.objgen
        except Exception:
            oid = None
        if oid and oid != (0, 0):
            if oid in seen:
                return
            seen.add(oid)
        s = node.get("/S")
        if s is not None:
            name = str(s).lstrip("/")
            tags[name] += 1
            if len(name) == 2 and name[0] == "H" and name[1].isdigit():
                headings.append(name)
            if name == "Figure":
                alt = node.get("/Alt")
                figures.append({"alt": str(alt) if alt is not None else None})
        kids = node.get("/K")
        if kids is not None:
            visit(kids)

    root = pdf.Root.get("/StructTreeRoot")
    if root is not None:
        visit(root.get("/K"))
    return tags, headings, figures


@pytest.fixture(scope="module")
def walked(report):
    with pikepdf.open(str(report)) as pdf:
        return _walk(pdf)


# ── the document as a whole ──────────────────────────────────────────────────────────────────

def test_the_document_declares_language_title_and_tagging(report):
    """3.1.1 language, 2.4.2 title, and the tagging flags — the three the engine's own rules
    check, asserted on the real catalog rather than on the renderer's intent."""
    with pikepdf.open(str(report)) as pdf:
        root = pdf.Root
        assert str(root.get("/Lang")) == "en-US"
        assert bool((root.get("/MarkInfo") or {}).get("/Marked")) is True
        assert "/StructTreeRoot" in root
        assert bool((root.get("/ViewerPreferences") or {}).get("/DisplayDocTitle")) is True
        assert root.get("/Metadata") is not None, "no XMP metadata stream — PDF/UA requires one"
        assert "Accessibility Assessment Report" in str(pdf.open_metadata().get("dc:title"))


def test_the_structure_tree_is_not_empty(walked):
    """The check that separates a real tree from report.py::_tag_pdf's empty one."""
    tags, _, _ = walked
    assert sum(tags.values()) > 100, f"suspiciously small tree: {dict(tags)}"


# ── headings and reading order ───────────────────────────────────────────────────────────────

def test_the_heading_outline_starts_at_h1_and_skips_no_level(walked):
    _, headings, _ = walked
    assert headings, "no headings in the structure tree"
    assert headings[0] == "H1", f"outline starts at {headings[0]}"
    levels = [int(h[1]) for h in headings]
    for prev, nxt in zip(levels, levels[1:]):
        assert nxt <= prev + 1, f"heading level jumps {prev} -> {nxt}: {headings}"


def test_every_section_has_a_heading(walked):
    """Five <section>s, five H2s. A section whose heading was dropped from the tree is a section
    a screen-reader user cannot navigate to."""
    tags, headings, _ = walked
    assert headings.count("H2") == tags["Sect"], (
        f"{tags['Sect']} sections but {headings.count('H2')} H2 headings")


# ── tables ───────────────────────────────────────────────────────────────────────────────────

def test_tables_carry_real_header_cells(walked):
    tags, _, _ = walked
    assert tags["Table"] >= 2, f"expected both data tables; got {tags['Table']}"
    assert tags["THead"] >= 2, "a table has no THead — header rows are not marked as headers"
    assert tags["TH"] >= 9, f"too few header cells: {tags['TH']}"
    assert tags["TD"] >= 1 and tags["TR"] >= 1


def test_every_table_row_has_a_row_header(walked):
    """Each row's first cell is a <th scope="row">, so a cell read out of context still says
    which file or criterion it belongs to. Column headers alone leave "55%" meaning nothing."""
    tags, _, _ = walked
    # 5 column headers + 4 column headers = 9; the rest are row headers, one per body row.
    assert tags["TH"] > 9, (
        f"only {tags['TH']} TH cells — that is column headers alone, with no row headers")


# ── charts: the thing a conformant-but-worse render silently loses ───────────────────────────

def test_every_chart_is_a_figure_with_a_conclusion_stating_alt(walked):
    """THE load-bearing test in this file.

    The shipped template's inline <svg> charts are invisible to WeasyPrint's tagger: rendered
    as-is the document still passes veraPDF with zero failures, and the charts are simply not in
    the tree. This asserts the treatment that fixes it — <img alt> — actually took, and that the
    alt says something a reader can use rather than naming the chart type.
    """
    _, _, figures = walked
    assert len(figures) >= 3, (
        f"expected the logo plus two charts as Figures; got {len(figures)}. If this is 1, the "
        f"charts have fallen back to inline SVG and are no longer in the reading order.")
    for fig in figures:
        assert fig["alt"], f"a Figure carries no /Alt: {fig}"
        assert len(fig["alt"]) > 3

    alts = " ".join(f["alt"] for f in figures)
    assert "out of 100" in alts, "the score ring's alt does not state the score"
    assert "affects the most files" in alts, "the bar chart's alt does not state its conclusion"


def test_the_chart_alt_reads_as_a_sentence(walked):
    """Alt text is READ ALOUD, so it has to parse. The first draft emitted "2 further criterions
    also has open issues" — a Figure with an /Alt, veraPDF-clean, and wrong in the one place only
    a screen-reader user would ever encounter."""
    _, _, figures = walked
    alts = " ".join(f["alt"] or "" for f in figures)
    assert "criterions" not in alts, f"bad plural in chart alt text: {alts}"
    assert "criteria also has" not in alts, f"subject/verb disagreement in chart alt text: {alts}"


def test_the_chart_numbers_are_also_in_a_real_table(walked):
    """The alt states a conclusion; the exact counts belong in the tag tree as data, not only as
    a picture. Two tables and their header cells are what make that true."""
    tags, _, _ = walked
    assert tags["Table"] >= 2 and tags["TD"] >= 8


# ── links ────────────────────────────────────────────────────────────────────────────────────

def test_the_standard_reference_is_a_real_link(walked):
    tags, _, _ = walked
    assert tags["Link"] >= 1, "no Link element — the WCAG reference is not a real link"


# ── the renderer degrades honestly ───────────────────────────────────────────────────────────

def test_a_run_with_no_score_omits_the_ring_rather_than_inventing_one(tmp_path):
    """avg_score is None for a run that produced no scores. The ring must disappear, not render
    a zero — a "0 out of 100" alt on a scan that was never scored is a fabricated finding."""
    out = _build(tmp_path, run={"avg_score": None})
    with pikepdf.open(str(out)) as pdf:
        _, _, figures = _walk(pdf)
    alts = " ".join(f["alt"] or "" for f in figures)
    assert "out of 100" not in alts, f"a score ring was rendered for an unscored run: {alts}"


def test_a_clean_run_still_produces_a_valid_tree(tmp_path):
    """No open issues means no bar chart and no findings table. The outline must survive it."""
    clean = [{"file": "a.pdf", "status": "done", "compliant": 1, "score": 100,
              "skipped_rules": 0, "issues": []}]
    out = _build(tmp_path, files=clean,
                 run={"files": 1, "certifiable": 1, "avg_score": 100})
    with pikepdf.open(str(out)) as pdf:
        tags, headings, figures = _walk(pdf)
    assert headings and headings[0] == "H1"
    assert tags["Table"] >= 1, "the file inventory table vanished on a clean run"
    for fig in figures:
        assert fig["alt"], "a Figure lost its /Alt on the clean-run path"


# ── the validator, when it is available ──────────────────────────────────────────────────────

@pytest.mark.skipif(not VERAPDF_OK, reason=NO_VERAPDF)
def test_the_report_is_pdfua_1_conformant(report):
    """The automated gate ADR 0034 requires. Structural correctness above is necessary and not
    sufficient — WeasyPrint's own documentation says selecting the pdf/ua-1 variant does not
    guarantee a conformant document."""
    result = validate(report)
    assert result.compliant, result.summary()
    assert result.failed_checks == 0


# ── fonts: the defect no structural check and no validator noticed ───────────────────────────

def _embedded_fonts(path: Path) -> set[str]:
    with pikepdf.open(str(path)) as pdf:
        out = set()
        for obj in pdf.objects:
            try:
                if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name("/Font"):
                    bf = obj.get("/BaseFont")
                    if bf is not None:
                        # Strip the six-letter subset prefix ("ABCDEF+").
                        out.add(str(bf).lstrip("/").split("+")[-1])
            except Exception:
                continue
        return out


def test_the_report_is_set_in_the_intended_sans_face(report):
    """THE REGRESSION THIS EXISTS FOR. The font stack was briefly passed through a Jinja
    variable; the environment autoescapes, so it reached the CSS as

        font-family: &#34;Liberation Sans&#34;, &#34;DejaVu Sans&#34;, Arial, sans-serif;

    which is invalid, silently ignored, and rendered the whole customer-facing report in
    WeasyPrint's default SERIF face. veraPDF passed with zero failures. Every structural test
    stayed green — tagging does not depend on the font. Only rendering the page and looking at
    it caught it, which is why this asserts on the embedded font rather than on the CSS text:
    the CSS is the mechanism, the embedded face is the property.
    """
    fonts = _embedded_fonts(report)
    # Production is Debian and deliberately installs Liberation Sans. Developer Macs resolve
    # the same CSS fallback to Arial instead; that is not evidence that the declaration was
    # ignored. The invariant is a real sans face, never WeasyPrint's serif default. A separate
    # deployment test below pins the production image's deterministic font package.
    assert any(("Liberation" in f) or ("Arial" in f) for f in fonts), (
        f"neither Liberation Sans nor its Arial fallback is embedded — the font stack is not "
        f"reaching the renderer. Embedded: {sorted(fonts)}")
    assert not any(("Serif" in f) or ("Charter" in f) or ("Times" in f) for f in fonts), (
        f"a serif face is embedded — the sans stack was ignored. Embedded: {sorted(fonts)}")


def test_the_tick_and_cross_glyphs_have_a_font_that_carries_them(report):
    """Liberation Sans has no U+2713 ✓ or U+2717 ✗ and the File Inventory table prints both, so
    a second face must be embedded to supply them. Without it they render as tofu — visible to a
    sighted reader, invisible to every automated check in this file."""
    fonts = _embedded_fonts(report)
    # macOS supplies these glyphs from Arial Unicode MS. Production deliberately installs
    # DejaVu; accepting the platform-equivalent face keeps this render test meaningful locally
    # without making the container's font selection ambient.
    assert any(("DejaVu" in f) or ("Arial-Unicode" in f) for f in fonts), (
        f"no symbol-capable fallback face is embedded — the ✓/✗ marks in the File Inventory "
        f"have no glyph source. Embedded: {sorted(fonts)}")


def test_the_runtime_declares_the_renderer_fonts_and_native_libraries():
    """Selecting the renderer must work in the deployed image, not only in a developer venv.

    PR #1159 added the module and its tests without adding WeasyPrint to the API requirements;
    it also relied on DejaVu while the image installed only Liberation. Both omissions allow a
    locally green PDF to fail at the first production request or render its symbols as tofu.
    """
    requirements = (ACP / "api/requirements.txt").read_text(encoding="utf-8").lower()
    base_image = (ACP / "deploy/public/Dockerfile.base-api").read_text(encoding="utf-8")
    fallback_image = (ACP / "deploy/public/Dockerfile").read_text(encoding="utf-8")
    assert "weasyprint==" in requirements
    required_apt = ("fonts-liberation", "fonts-dejavu-core", "libpango-1.0-0",
                    "libpangoft2-1.0-0", "libharfbuzz0b", "libfontconfig1")
    assert all(package in base_image for package in required_apt)
    # Dockerfile's from-scratch path must be complete too. Testing only the optimized base image
    # lets a clean build succeed and then fail at the first PDF request.
    assert all(package in fallback_image for package in required_apt)


def test_the_chart_alt_names_the_criterion_the_chart_actually_shows_as_largest():
    """The alt says "affects the most files" — so it must name the longest bar.

    `_bars_alt` receives its rows sorted by SEVERITY, and an earlier version read row[0] as the
    maximum. The two coincide in the sample fixture, so nothing here caught it; a real 37-file
    scan produced a report whose alt said "1.3.1 Info and Relationships affects the most files,
    37 of 37" while the longest bar on the same page was 2.4.2 Page Titled at 49. The sentence
    and the picture came from one list and disagreed.

    That is the failure this whole file exists for: a Figure with an /Alt, veraPDF green, every
    structural assertion passing, and the only reader affected is the one who cannot see the
    chart being told the wrong thing. The rows below are in severity order with the largest count
    LAST, which is the arrangement the bug needs.
    """
    import report_weasy
    rows = [("1.3.1 Info and Relationships", 37),    # Critical, sorts first
            ("2.4.1 Bypass Blocks", 12),
            ("2.4.2 Page Titled", 49)]              # Moderate, sorts last, but is the largest
    alt = report_weasy._bars_alt(rows, 37)
    assert "2.4.2 Page Titled affects the most files, 49" in alt, alt
    assert "1.3.1" not in alt.split("affects the most files")[0], (
        f"named the highest-severity row rather than the largest: {alt}")


def test_the_chart_alt_breaks_a_tie_toward_the_more_severe_criterion():
    """Equal counts keep the earlier row, which is the higher-severity one.

    Pinned because `max` returning the first maximum is a property of the implementation, and
    the sentence reads better naming the criterion a reader should care about first.
    """
    import report_weasy
    alt = report_weasy._bars_alt([("1.3.1 Info and Relationships", 37),
                                  ("3.1.1 Language of Page", 37)], 37)
    assert "1.3.1 Info and Relationships affects the most files, 37 of 37" in alt, alt
