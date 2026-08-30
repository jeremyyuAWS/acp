"""The labelled .xlsx ground-truth corpus — and the check that its labels are earned.

`scripts/gen_fixture_coverage.py` reported 15 of 62 pairs covered: .docx complete, xlsx / pptx /
pdf at zero. This is the start of xlsx, and it is deliberately partial — four pairs, not fifteen.

THE LIMIT IS VERIFICATION, NOT EFFORT, and that distinction is the whole reason this file matters
more than the generator. Coverage is counted from DECLARATIONS, so a fixture that declares
"1.4.3: FAIL" while seeding something no detector catches would raise the coverage number without
raising the coverage. These tests refuse that trade: every violation fixture is driven through
the real first-party detector and asserted to fire, and every adversarial fixture is asserted to
stay silent. A declaration in the manifest is therefore a measured fact.

The remaining eleven .xlsx pairs are absent because their detection runs through the .NET Office
analyser, or (3.1.2) through langdetect — neither installable in every environment, and a label
nobody can confirm is exactly what this file exists to prevent.

WHY THE ADVERSARIAL FIXTURES ARE HALF THE CORPUS. A corpus of obvious violations measures almost
nothing: anything finds white-on-white text. What separates a detector from a regex is the
near-miss — a LONE default 'Sheet1' tab, which Excel gives every new workbook and which must not
be flagged; an iconSet, which pairs colour WITH a shape and is therefore not colour-only. Each of
those names the specific wrong answer it is built to catch.
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
    "gen_xlsx_corpus", ROOT / "scripts" / "gen_xlsx_corpus.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_xlsx_corpus"] = gen
_spec.loader.exec_module(gen)

import corpus_expectations as ce  # noqa: E402
from engines import NO_OFFICE, OFFICE_OK  # noqa: E402


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Build every fixture once. Generated, not committed: a generated corpus cannot drift from
    the generator that documents what each fixture is FOR, and it keeps binaries whose provenance
    a reviewer would have to take on trust out of the repo."""
    out = tmp_path_factory.mktemp("xlsx-corpus")
    manifest, problems = gen.build_all(out / "docs")
    assert not problems, f"fixtures declare verdicts the engine cannot emit: {problems}"
    return out, {row["name"]: row for row in manifest}


def _wcags(path: Path) -> set[str]:
    """Criteria the FIRST-PARTY xlsx checks report — pure Python, no external engine."""
    return {(f.get("wcag") or "").split()[0] for f in osx.checks_for(path, ".xlsx")
            if f.get("wcag")}


# ── the labels are legal for their lane ──────────────────────────────────────────

def test_every_declaration_is_a_verdict_the_engine_can_emit(corpus):
    """The generator enforces this at build time; asserting it here too means a fixture cannot be
    added with an impossible label by someone who never runs the generator directly."""
    _out, rows = corpus
    for name, row in rows.items():
        for sc, verdict in row["expect"].items():
            allowed = ce.possible_verdicts(sc, "xlsx")
            assert verdict in allowed, (
                f"{name} expects {sc}={verdict}, but ({sc}, xlsx) can only emit "
                f"{sorted(allowed)}")


def test_no_review_lane_fixture_claims_pass(corpus):
    """The specific trap corpus_expectations exists for. 1.4.1, 2.4.4 and 2.4.6 are review-lane on
    .xlsx: a CLEAN file there resolves to REVIEW and never to PASS, so an adversarial fixture that
    expected PASS would report a false failure forever and read as a product defect."""
    _out, rows = corpus
    for name, row in rows.items():
        for sc, verdict in row["expect"].items():
            if not ce.can_ever_pass(sc, "xlsx"):
                assert verdict != "PASS", (
                    f"{name} expects PASS on {sc}, which .xlsx cannot certify (ADR 0016)")


# ── the labels are EARNED: the detector actually fires ───────────────────────────

@pytest.mark.parametrize("name,sc", [
    ("contrast-fail", "1.4.3"),
    ("link-vague", "2.4.4"),
    ("sheet-tabs-default", "2.4.6"),
    ("colour-scale-only", "1.4.1"),
    ("image-no-alt", "1.1.1"),
    ("shape-faint-outline", "1.4.11"),
    ("form-control", "4.1.2"),
    ("form-control", "2.1.2"),
])
def test_each_violation_fixture_is_actually_detected(corpus, name, sc):
    """Without this, a declaration is a hope. Coverage is counted from declarations, so an
    undetected fixture would raise the number #1009 reports without raising what it measures."""
    out, _rows = corpus
    got = _wcags(out / "docs" / f"{name}.xlsx")
    assert sc in got, (
        f"{name} seeds a {sc} violation that no first-party detector catches — the manifest "
        f"would claim coverage the corpus does not have. Detected: {sorted(got) or 'nothing'}")


@pytest.mark.parametrize("name,sc", [
    ("link-descriptive-ok", "2.4.4"),
    ("sheet-tab-single-ok", "2.4.6"),
    ("sheet-tabs-named-ok", "2.4.6"),
    ("colour-icon-set-ok", "1.4.1"),
    ("contrast-ok", "1.4.3"),
    ("no-image-ok", "1.1.1"),
    ("shape-strong-outline-ok", "1.4.11"),
    ("no-controls-ok", "4.1.2"),
    ("no-controls-ok", "2.1.2"),
])
def test_each_adversarial_fixture_stays_silent(corpus, name, sc):
    """The half that separates a detector from a regex. A false positive is cheap to ship and
    expensive to trust: it is what teaches a reviewer to stop reading the findings."""
    out, _rows = corpus
    got = _wcags(out / "docs" / f"{name}.xlsx")
    assert sc not in got, (
        f"{name} is a false positive on {sc} — it is the case the detector is supposed to let "
        f"through. Detected: {sorted(got)}")


def test_one_control_answers_for_both_its_criteria(corpus):
    """An embedded control is evidence for the accessible-name question AND the keyboard-trap
    question, and the detector reports both — so one fixture legitimately covers two pairs.
    Asserted together because a change that dropped either would still pass the other's
    parametrised case above and look fine."""
    out, _rows = corpus
    got = _wcags(out / "docs" / "form-control.xlsx")
    assert {"4.1.2", "2.1.2"} <= got, f"the control fired only {sorted(got)}"


def test_the_faint_outline_is_measured_not_assumed(corpus):
    """Both shape fixtures carry the SAME shape; only the outline colour differs. If the detector
    ever started reporting on the presence of a shape rather than on its measured ratio, the
    adversarial case would fire too — which is the whole distinction 1.4.11 turns on."""
    out, _rows = corpus
    assert "1.4.11" in _wcags(out / "docs" / "shape-faint-outline.xlsx")
    assert "1.4.11" not in _wcags(out / "docs" / "shape-strong-outline-ok.xlsx")


def test_the_lone_default_tab_is_the_edge_case_it_claims_to_be(corpus):
    """Named separately because it is the one most likely to be 'fixed' into a bug. Excel titles
    every new workbook's first sheet 'Sheet1'; flagging one would fire on most files in an
    estate, so the detector requires two before it says anything. Three tabs fire; one does not."""
    out, _rows = corpus
    assert "2.4.6" in _wcags(out / "docs" / "sheet-tabs-default.xlsx")
    assert "2.4.6" not in _wcags(out / "docs" / "sheet-tab-single-ok.xlsx")


# ── the corpus and the coverage report agree ─────────────────────────────────────

def test_the_coverage_report_counts_this_corpus(corpus):
    """The generator, the report and the ratchet's baseline are one fact in three places; this is
    what stops them drifting."""
    import gen_fixture_coverage as gfc
    cov = gfc.coverage()
    assert cov["xlsx"]["has_generator"] is True, (
        "gen_fixture_coverage does not know about the xlsx corpus — add it to GENERATORS")
    declared = set(gen.DECLARED) | set(gen.DECLARED_ENGINE)
    assert sorted(cov["xlsx"]["covered"]) == sorted(declared)
    assert gfc.BASELINE["xlsx"] == len(declared), (
        f"BASELINE['xlsx'] is {gfc.BASELINE['xlsx']} but the corpus declares "
        f"{len(declared)} — the ratchet would have slack in it")
    assert sorted(cov["xlsx"]["engine_only"]) == sorted(gen.DECLARED_ENGINE), (
        "the report's engine-only split disagrees with the generator — the headline number "
        "would then imply a guarantee two of these pairs do not have")


def test_the_declared_set_matches_what_the_fixtures_actually_declare(corpus):
    """DECLARED is written down for the report to read; this keeps it honest against the
    fixtures themselves."""
    _out, rows = corpus
    from_fixtures = {sc for row in rows.values() for sc in row["expect"]}
    assert from_fixtures == set(gen.DECLARED) | set(gen.DECLARED_ENGINE)


# ── the engine-verified pairs: structure here, detection in CI ───────────────────

def _core_xml(path: Path) -> str:
    import zipfile
    with zipfile.ZipFile(path) as z:
        return z.read("docProps/core.xml").decode("utf-8")


def _prop(xml: str, tag: str) -> str | None:
    """A core-property value, or None when the element is absent.

    The regex allows attributes on the element — openpyxl writes `<dc:title xmlns:dc="...">`,
    not `<dc:title>`, and a pattern without that allowance silently reports every fixture as
    having no title. (It did, on the first run of this check.)"""
    import re
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("name,tag,present", [
    ("no-document-title", "dc:title", False),
    ("document-title-ok", "dc:title", True),
    ("no-document-language", "dc:language", False),
    ("document-language-ok", "dc:language", True),
])
def test_the_engine_fixtures_carry_or_withhold_the_right_property(corpus, name, tag, present):
    """What this file CAN prove without the .NET analyser, and the half that actually rots.

    Detection for 2.4.2 and 3.1.1 is asserted below, gated on the engine. But a fixture silently
    losing the property it was built around is a corpus defect that no engine is needed to catch
    — and it is the likelier failure, because it happens whenever someone edits the base workbook
    rather than the fixture. Splitting the two means a broken fixture fails everywhere, and only
    the detection claim waits for CI."""
    out, rows = corpus
    xml = _core_xml(out / rows[name]["file"])
    value = _prop(xml, tag)
    if present:
        assert value, f"{name} should carry a non-empty <{tag}> and has {value!r}"
    else:
        assert not value, f"{name} deliberately withholds <{tag}> but carries {value!r}"


def test_every_other_fixture_declares_both_a_title_and_a_language(corpus):
    """The correctness fix this pair of criteria surfaced, pinned so it cannot regress.

    openpyxl leaves `properties.language` at None, and XLSX-LANG-001 reports 3.1.1 for exactly
    that — so before the base workbook set one, EVERY fixture here also carried a 3.1.1 finding
    under the engine. The single-criterion labels were true only because a bare container has no
    .NET, which is the worst way for a ground-truth corpus to be right."""
    out, rows = corpus
    withholding = {"no-document-title": "dc:title", "no-document-language": "dc:language"}
    for name, row in rows.items():
        xml = _core_xml(out / row["file"])
        for tag in ("dc:title", "dc:language"):
            if withholding.get(name) == tag:
                continue
            assert _prop(xml, tag), (
                f"{name} has no <{tag}> — under the .NET analyser it would also raise "
                f"{'2.4.2' if tag == 'dc:title' else '3.1.1'}, so its label is wrong in CI")


@pytest.mark.skipif(not OFFICE_OK, reason=NO_OFFICE)
@pytest.mark.parametrize("name,sc,fires", [
    ("no-document-title", "2.4.2", True),
    ("document-title-ok", "2.4.2", False),
    ("no-document-language", "3.1.1", True),
    ("document-language-ok", "3.1.1", False),
])
def test_the_engine_confirms_the_declared_pairs(corpus, name, sc, fires):
    """The detection half — and the reason these two pairs sit in DECLARED_ENGINE rather than
    DECLARED. No first-party Python detector exists for 2.4.2 or 3.1.1 on ANY Office format, so
    unlike every other pair in this corpus the label is proven where the analyser is built and
    skipped where it is not.

    That is a weaker guarantee, and it is still worth having: both are among the seventeen
    (criterion, format) pairs in the preset that can return a PASS, so before these fixtures a
    clean scan CERTIFIED the file against a criterion nothing in the suite checked."""
    from scanner import analyse_and_assess
    out, rows = corpus
    path = out / rows[name]["file"]
    fd, _ = analyse_and_assess(path.parent, path.name, detect_pii=False)
    found = {(i.get("wcag") or "").split()[0] for i in (fd or {}).get("issues", [])}
    if fires:
        assert sc in found, (
            f"{name} declares {sc} but the analyser reported {sorted(found) or 'nothing'}")
    else:
        assert sc not in found, f"{name} is the clean control for {sc} but the analyser flagged it"
