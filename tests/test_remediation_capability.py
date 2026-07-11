"""Prove the capability table (api/remediation_capability.py) against reality.

The table declares HOW each (format, criterion) is actioned — auto / assisted / human. These
tests make that a checked contract, not an assertion: an "auto" lane that doesn't actually
clear on re-scan, an "assisted" lane with no proposer, or any drift vs store.RULE_FORMATS
fails the build. That is what lets the product say "100% actioned" and mean it.
"""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import remediation_capability as cap  # noqa: E402
from store import RULE_FORMATS  # noqa: E402


def _inscope(fmt: str) -> set[str]:
    return {sc for sc, fmts in RULE_FORMATS.items() if fmt in fmts}


def _sc(wcag: str) -> str:
    w = (wcag or "").strip()
    return w[3:].replace("_", ".") if w.startswith("SC_") else w.split(" ", 1)[0]


# ── the table is well-formed and in lock-step with RULE_FORMATS ────────────────

def test_all_lanes_are_valid():
    for fmt, lanes in cap.CAPABILITY.items():
        for sc, ln in lanes.items():
            assert ln in cap.LANES, f"{fmt}/{sc} has invalid lane {ln!r}"


@pytest.mark.parametrize("fmt", sorted(cap.CAPABILITY))
def test_capability_matches_rule_formats_exactly(fmt):
    have = set(cap.CAPABILITY[fmt])
    want = _inscope(fmt)
    missing = want - have
    orphan = have - want
    assert not missing, f"{fmt}: in-scope criteria with no capability lane: {sorted(missing)}"
    assert not orphan, f"{fmt}: capability entries not in RULE_FORMATS for {fmt}: {sorted(orphan)}"


def test_every_inscope_criterion_is_covered_across_all_formats():
    # nothing in-scope anywhere is missing from the table
    for sc, fmts in RULE_FORMATS.items():
        for fmt in fmts:
            assert cap.lane(fmt, sc) is not None, f"{fmt}/{sc} in RULE_FORMATS but no lane"


def test_actioned_summary_totals():
    # every in-scope criterion lands in exactly one lane (auto+assisted+human == total)
    for fmt in ("docx", "xlsx", "pdf", "pptx"):
        s = cap.actioned_summary(fmt)
        assert s[cap.AUTO] + s[cap.ASSISTED] + s[cap.HUMAN] == s["total"] == len(_inscope(fmt))


# ── the "auto" lanes actually clear on re-scan (docx/xlsx, via the demo fixtures) ──

@pytest.fixture(scope="module")
def remediated_residual(tmp_path_factory):
    """Scan the demo fixtures, remediate, re-scan; return {fmt: set(SCs still firing)} plus
    whether the .NET engine ran. Skips cleanly if the fixtures or engine aren't present."""
    import scanner
    import remediate_office
    fixtures = {
        "docx": ROOT / "demo-fixtures" / "word-accessibility-demo.docx",
        "xlsx": ROOT / "demo-fixtures" / "excel-accessibility-demo.xlsx",
    }
    if not all(p.exists() for p in fixtures.values()):
        pytest.skip("demo fixtures not present")
    out = {}
    engine_ran = False
    for fmt, src in fixtures.items():
        # Copy into a tmp dir FIRST — remediate_office writes 'remediated-<name>' next to its
        # input, so remediating the source in place would pollute the committed demo-fixtures/.
        work = tmp_path_factory.mktemp("cap-src")
        wsrc = work / src.name
        shutil.copy(src, wsrc)
        before, _ = scanner.analyse_and_assess(work, src.name, detect_pii=False)
        engine_ran = engine_ran or any(str(i.get("wcag", "")).startswith("SC_") for i in before.get("issues", []))
        fixed, _applied, _skipped = remediate_office.remediate_office(wsrc, ai_enabled=False)
        if fixed is None:
            out[fmt] = {_sc(i.get("wcag", "")) for i in before.get("issues", [])}
            continue
        d = tmp_path_factory.mktemp("cap-rem")
        rname = "rem-" + src.name
        shutil.copy(fixed, d / rname)
        after, _ = scanner.analyse_and_assess(d, rname, detect_pii=False)
        out[fmt] = {_sc(i.get("wcag", "")) for i in after.get("issues", [])}
    return {"residual": out, "engine_ran": engine_ran}


@pytest.mark.parametrize("fmt", ["docx", "xlsx"])
def test_auto_lanes_clear_on_rescan(remediated_residual, fmt):
    if not remediated_residual["engine_ran"]:
        pytest.skip("the .NET office analysers did not run (CLI not built)")
    residual = remediated_residual["residual"][fmt]
    auto = {sc for sc, ln in cap.CAPABILITY[fmt].items() if ln == cap.AUTO}
    still_firing = auto & residual
    assert not still_firing, (
        f"{fmt}: these SCs are marked 'auto' but did NOT clear on re-scan — fix the lane, not "
        f"the test: {sorted(still_firing)}")


# ── the "assisted" lanes have a proposer wired ────────────────────────────────

def test_assisted_lanes_have_a_proposer():
    # The proposer machinery for the assisted criteria must exist (smoke — guards against an
    # 'assisted' claim with nothing behind it). These are the format-agnostic proposers +
    # the office/pdf alt paths.
    import proposals
    for fn in ("propose_language_parts", "propose_sensory_rewrite", "propose_images_of_text"):
        assert callable(getattr(proposals, fn, None)), f"proposals.{fn} missing"
    # 1.1.1 alt is proposed in the office/pdf remediators (vision path) — assert those modules import.
    import remediate_office, remediate_pdf  # noqa: F401
