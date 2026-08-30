"""The labelled .pdf ground-truth corpus — and the check that its labels are earned.

Fourth and last format, same rule as .xlsx and .pptx before it: a pair is declared only when a
FIRST-PARTY detector was driven against the fixture and confirmed to fire, with an adversarial
counterpart confirmed to stay silent. Coverage is counted from declarations, so an undetected
fixture would raise the number gen_fixture_coverage reports without raising what it measures.

PDF IS THE ONE FORMAT WHOSE ENGINE IS ALWAYS PRESENT. The analyser is vendored in-tree (ADR
0029), so unlike the .NET Office analyser these tests exercise real detection everywhere the
suite runs rather than skipping in a bare container. That is why this file drives
`office_structure.checks_for(path, ".pdf")` — the real dispatch, all twelve pdf detectors —
rather than calling each detector directly: it tests what a scan actually does, and it is what
catches a fixture that trips a criterion it did not mean to.

EVERY FIXTURE IS SINGLE-CRITERION, and on PDF that took deliberate work rather than being free:

  * 1.4.1 and 2.4.4 read the SAME hyperlink. The 1.4.1 fixture is a descriptive label with the
    underline suppressed; the 2.4.4 fixture is a vague label WITH an underline. Swap either and
    one fixture measures two things at once. Both separations are asserted below, because the
    parametrised sweep alone would still pass if a fixture quietly grew a second finding.
  * 2.4.6 needs six pages to clear its five-page floor — and 2.4.1 applies that same floor to a
    file with an empty outline, so six blank pages raise 2.4.1 too. The fixtures carry a
    bookmark for no reason other than staying single-criterion.

THE ONE EXCEPTION, asserted rather than hidden: the 1.4.3 violation also raises 1.4.6. One
measurement (~1.9:1) fails the AA and AAA bars at once and one detector emits both, so this is
inherent and not a fixture defect. Neither 1.4.6 nor 2.4.1 is in the preset, so neither moves
the coverage count.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import office_structure as osx  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "gen_pdf_corpus", ROOT / "scripts" / "gen_pdf_corpus.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_pdf_corpus"] = gen
_spec.loader.exec_module(gen)

import corpus_expectations as ce  # noqa: E402


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("pdf-corpus")
    manifest, problems = gen.build_all(out / "docs")
    assert not problems, f"fixtures declare verdicts the engine cannot emit: {problems}"
    return out, {row["name"]: row for row in manifest}


_ENGINE = ROOT / "engine" / "pdf-analyser"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

def _catalog_wcags(path: Path) -> set[str]:
    """The criteria the VENDORED analyser's catalog rules report — 2.4.2 and 3.1.1, which do not
    go through office_structure.checks_for. Kept separate from the import above so that a
    truncated checkout fails this file loudly rather than silently reporting a clean scan."""
    import pdfplumber
    import pikepdf
    from analysers.rules.pdf.document_language import DocumentLanguageRule
    from analysers.rules.pdf.document_title import DocumentTitleRule

    found: set[str] = set()
    with pikepdf.open(str(path)) as pk, pdfplumber.open(str(path)) as pl:
        for rule in (DocumentTitleRule(), DocumentLanguageRule()):
            for issue in rule.check(pk, pl):
                name = issue.wcag_criterion.name           # e.g. "SC_2_4_2"
                found.add(".".join(name.removeprefix("SC_").split("_")))
    return found


def _wcags(path: Path) -> set[str]:
    """Every criterion a real scan of this file reports, across BOTH pdf code paths.

    The union is what makes the single-criterion assertions below mean anything. Checking only
    `checks_for` would miss 2.4.2 and 3.1.1 — which every fixture would otherwise raise, since a
    freshly authored PDF carries neither /Title nor /Lang. The generator stamps both onto every
    fixture that is not testing their absence, and this union is what proves it did."""
    structural = {(f.get("wcag") or "").split()[0] for f in osx.checks_for(path, ".pdf")
                  if f.get("wcag")}
    return structural | _catalog_wcags(path)


def _path(corpus, name: str) -> Path:
    out, rows = corpus
    return out / rows[name]["file"]


# ── the labels are legal for their lane ──────────────────────────────────────────

def test_every_declaration_is_a_verdict_the_engine_can_emit(corpus):
    _out, rows = corpus
    for name, row in rows.items():
        for sc, verdict in row["expect"].items():
            allowed = ce.possible_verdicts(sc, "pdf")
            assert verdict in allowed, (
                f"{name} expects {sc}={verdict}, but ({sc}, pdf) can only emit {sorted(allowed)}")


CERTIFIABLE = ("1.4.3", "2.4.2", "3.1.1")


def test_only_the_certifiable_pairs_claim_pass(corpus):
    """Three of the ten declared .pdf pairs can ever certify — 1.4.3, 2.4.2 and 3.1.1, all in the
    assessment AUTO lane. The other seven are review-lane and may never expect PASS however clean
    the fixture is (ADR 0016). Asserted in both directions so a lane change on either side has to
    be noticed here rather than silently turning a control's verdict into a false claim."""
    _out, rows = corpus
    for name, row in rows.items():
        for sc, verdict in row["expect"].items():
            if not ce.can_ever_pass(sc, "pdf"):
                assert verdict != "PASS", (
                    f"{name} expects PASS on {sc}, which .pdf cannot certify")
    for sc in CERTIFIABLE:
        assert ce.can_ever_pass(sc, "pdf"), (
            f"{sc} stopped being certifiable on pdf — its control's PASS is now a false claim")


# ── the labels are EARNED ────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,sc", [
    ("figure-no-alt", "1.1.1"),
    ("link-colour-only", "1.4.1"),
    ("contrast-fail", "1.4.3"),
    ("rect-faint-outline", "1.4.11"),
    ("no-document-title", "2.4.2"),
    ("no-tabs-structure", "2.4.3"),
    ("link-vague", "2.4.4"),
    ("no-headings", "2.4.6"),
    ("no-document-language", "3.1.1"),
    ("field-no-name", "4.1.2"),
])
def test_each_violation_fixture_is_actually_detected(corpus, name, sc):
    """The load-bearing test. A declared pair whose fixture nothing detects inflates coverage
    without adding any."""
    fired = _wcags(_path(corpus, name))
    assert sc in fired, (
        f"{name} declares {sc} but a real scan reported {sorted(fired) or 'nothing'} — the "
        f"fixture does not carry the violation it claims")


@pytest.mark.parametrize("name,sc", [
    ("figure-with-alt-ok", "1.1.1"),
    ("link-underlined-ok", "1.4.1"),
    ("contrast-ok", "1.4.3"),
    ("rect-strong-outline-ok", "1.4.11"),
    ("document-title-ok", "2.4.2"),
    ("tabs-structure-ok", "2.4.3"),
    ("link-descriptive-ok", "2.4.4"),
    ("headings-ok", "2.4.6"),
    ("document-language-ok", "3.1.1"),
    ("field-named-ok", "4.1.2"),
])
def test_each_adversarial_fixture_stays_silent(corpus, name, sc):
    """Without these a detector that fires on everything would score full marks."""
    fired = _wcags(_path(corpus, name))
    assert sc not in fired, (
        f"{name} is the clean counterpart for {sc} but a real scan flagged it — a false positive")


def test_every_violation_has_a_paired_adversarial_fixture(corpus):
    """A corpus that grows a violation without its control has quietly stopped measuring false
    positives for that criterion, and nothing else in the suite would notice. Asserted as set
    EQUALITY so a drift in either direction fails."""
    _out, rows = corpus
    violation = {sc for r in rows.values() if r["kind"] == "violation" for sc in r["expect"]}
    adversarial = {sc for r in rows.values() if r["kind"] == "adversarial" for sc in r["expect"]}
    assert violation == adversarial, (
        f"unpaired criteria: violations without a control {sorted(violation - adversarial)}, "
        f"controls without a violation {sorted(adversarial - violation)}")


# ── the fixtures are single-criterion, which is what makes a result attributable ──

@pytest.mark.parametrize("name,sc", [
    ("figure-no-alt", "1.1.1"),
    ("link-colour-only", "1.4.1"),
    ("rect-faint-outline", "1.4.11"),
    ("no-document-title", "2.4.2"),
    ("no-tabs-structure", "2.4.3"),
    ("link-vague", "2.4.4"),
    ("no-headings", "2.4.6"),
    ("no-document-language", "3.1.1"),
    ("field-no-name", "4.1.2"),
])
def test_each_violation_fixture_trips_exactly_one_criterion(corpus, name, sc):
    """A fixture that raises two findings cannot say which change the detector reacted to, and
    it silently makes the corpus's per-criterion counts wrong. Because `_wcags` unions both pdf
    code paths, this is also what proves the generator stamped /Title and /Lang onto every
    fixture: without the stamp all nine of these would additionally raise 2.4.2 and 3.1.1.

    contrast-fail is excluded and covered by its own test below — its second finding is
    inherent, not a defect."""
    fired = _wcags(_path(corpus, name))
    assert fired == {sc}, f"{name} should trip only {sc} but a real scan reported {sorted(fired)}"


def test_every_adversarial_fixture_is_completely_clean(corpus):
    """Stronger than the per-criterion silence above: the controls raise NOTHING at all. That is
    what makes them usable as false-positive ground truth for the whole format rather than only
    for the criterion they are paired with."""
    _out, rows = corpus
    for name, row in rows.items():
        if row["kind"] != "adversarial":
            continue
        fired = _wcags(_path(corpus, name))
        assert fired == set(), f"{name} is a clean control but a real scan reported {sorted(fired)}"


def test_an_unpainted_page_is_measured_against_white_not_abstained_on(tmp_path):
    """PDF does NOT inherit pptx's explicit-fill trap, and this test exists because the first
    draft of gen_pdf_corpus.py claimed it did. On pptx a bare textbox has no fill, so the
    detector cannot know what the text sits on and correctly says nothing. On PDF
    `_pdf_char_background` falls through to `_PDF_DEFAULT_BG` ("FFFFFF"), so a page with nothing
    drawn on it is measured against white and the finding stands.

    The claim was caught by deleting the fixture's background rect and finding every test still
    passing — a bite check that did not bite. Asserting the real behaviour here means the next
    person reads it off a test rather than off a paragraph that was wrong.
    """
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    def _draw(path, ground):
        c = canvas.Canvas(str(path), pagesize=gen._PAGE)
        if ground:
            c.setFillColor(HexColor(gen.PAPER))
            c.rect(0, 0, gen._PAGE[0], gen._PAGE[1], stroke=0, fill=1)
        c.setFillColor(HexColor(gen.GREY))
        c.setFont("Helvetica", 12)
        c.drawString(50, 120, "Quarterly compliance summary")
        c.save()

    painted, bare = tmp_path / "painted.pdf", tmp_path / "bare.pdf"
    _draw(painted, True)
    _draw(bare, False)

    def _ratios(p):
        return [f["evidence"]["value"] for f in osx.pdf_contrast_checks(p)]

    assert _ratios(bare), "an unpainted page stopped being measured — PDF now abstains like pptx"
    assert _ratios(bare) == _ratios(painted), (
        "painting the page's own background changed the measured ratio — the default ground is "
        "no longer the same colour the fixture paints")
    assert osx._PDF_DEFAULT_BG.upper() == gen.PAPER.lstrip("#").upper(), (
        "the detector's default background and the fixture's painted ground have diverged")


def test_the_contrast_violation_also_raises_aaa_and_that_is_inherent(corpus):
    """The one fixture that is not single-criterion, asserted so it stays a known fact rather
    than becoming a surprise. ~1.9:1 fails 4.5:1 (AA) and 7:1 (AAA) at once, and
    pdf_contrast_checks emits both from the one measurement — there is no fixture that fails AA
    without failing AAA. 1.4.6 is outside the preset, so it does not move the coverage count."""
    fired = _wcags(_path(corpus, "contrast-fail"))
    assert fired == {"1.4.3", "1.4.6"}, (
        f"the contrast fixture now reports {sorted(fired)} — if 1.4.6 has gone, the AAA bar "
        f"changed; if something else appeared, the fixture stopped being about contrast")


# ── the two separations PDF makes hard, asserted directly ────────────────────────

def test_the_colour_only_link_is_not_also_a_vague_label(corpus):
    """1.4.1 and 2.4.4 read the same hyperlink, so the 1.4.1 fixture's label must be descriptive.
    Were it "Click here" this fixture would trip both and neither result would be attributable."""
    fired = _wcags(_path(corpus, "link-colour-only"))
    assert "2.4.4" not in fired, (
        "the 1.4.1 fixture's link label is vague enough to trip 2.4.4 as well — give it a label "
        "that names its destination")


def test_the_vague_link_is_underlined_so_it_does_not_also_trip_1_4_1(corpus):
    """The other half of the same separation. Without the underline this fixture would raise
    1.4.1 too, and the 2.4.4 count would be measuring the missing cue as well as the label."""
    fired = _wcags(_path(corpus, "link-vague"))
    assert "1.4.1" not in fired, (
        "the 2.4.4 fixture's link has no non-colour cue, so it trips 1.4.1 as well — underline it")


def test_the_two_link_fixtures_differ_only_in_label_and_underline(corpus):
    """Both point at the same destination. A control that also changed the URL could not show
    that the label is what the detector read."""
    _out, rows = corpus
    for name in ("link-colour-only", "link-vague", "link-descriptive-ok", "link-underlined-ok"):
        assert rows[name]["expect"], f"{name} declares nothing"
    import pdfplumber
    urls = set()
    for name in ("link-colour-only", "link-vague"):
        with pdfplumber.open(str(_path(corpus, name))) as pdf:
            urls |= {link.get("uri") for link in (pdf.pages[0].hyperlinks or [])}
    assert urls == {gen.LINK_URL}, (
        f"the link fixtures point at {urls}, not the one shared destination — the difference "
        f"between them must be the label and the underline, nothing else")


# ── the declared set and the generator agree ─────────────────────────────────────

def test_declared_matches_what_the_fixtures_actually_declare(corpus):
    """gen_fixture_coverage reads gen_pdf_corpus.DECLARED rather than building the fixtures, so
    the constant has to be held honest against them or the coverage report is a claim about a
    tuple somebody typed."""
    _out, rows = corpus
    actual = {sc for r in rows.values() for sc in r["expect"]}
    assert actual == set(gen.DECLARED), (
        f"DECLARED says {sorted(gen.DECLARED)} but the fixtures declare {sorted(actual)}")


def test_every_declared_pair_is_in_the_shipped_preset(corpus):
    """A fixture may legitimately exercise a criterion outside the preset (1.4.6 and 2.4.1 both
    turn up above), but a DECLARED one outside it would inflate coverage against a denominator
    that does not contain it."""
    applicable = {sc for sc, fmts in ce.pol.SCOPE_PRESETS["acp-core-17"].items() if "pdf" in fmts}
    assert set(gen.DECLARED) <= applicable, (
        f"declared but not applicable to pdf in the preset: "
        f"{sorted(set(gen.DECLARED) - applicable)}")


def test_the_coverage_report_counts_this_corpus(corpus):
    import gen_fixture_coverage as gfc
    cov = gfc.coverage()
    assert cov["pdf"]["has_generator"] is True, (
        "gen_fixture_coverage does not know about the pdf corpus — add it to GENERATORS")
    assert sorted(cov["pdf"]["covered"]) == sorted(gen.DECLARED)
    assert gfc.BASELINE["pdf"] == len(gen.DECLARED), (
        f"BASELINE['pdf'] is {gfc.BASELINE['pdf']} but the corpus declares "
        f"{len(gen.DECLARED)} — the ratchet would have slack in it")


def test_the_corpus_is_reachable_without_the_dotnet_engine():
    """The reason pdf reaches eight pairs from a standing start where xlsx needed zip-part
    injection: its analyser is vendored (ADR 0029), so these tests are not conditional on an
    engine a bare container lacks. If this ever starts skipping, the corpus stopped being
    ground truth everywhere and became ground truth on one developer's laptop."""
    import importlib.util as iu
    spec = iu.spec_from_file_location("check_engines", ROOT / "scripts" / "check_engines.py")
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    missing = mod.check(["pdf"])
    assert not missing, f"the pdf engine is unavailable here: {missing}"
