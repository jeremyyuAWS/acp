"""The operator scope has to gate the OFFICE and PDF deterministic fixers, not just proposals.

#137 gated the proposal lane and the HTML fixer and recorded the rest as a known gap
(`remediate.scope_partial`), because the office/pdf remediators apply their fixes inline inside
per-format functions with no per-rule boundary. That gap is what this module pins closed.

The load-bearing test here is `test_an_empty_scope_applies_nothing`. Every other test names a
criterion, so every other test can be made to pass by gating exactly the criteria somebody
thought of — which is the failure mode the whole feature exists to prevent. The empty-scope case
names none: it asserts that when the operator excludes EVERYTHING, the remediator writes nothing
at all. A newly added fixer that forgets its gate fails that test without anyone having to
remember to extend a list.

Fixtures come from scripts/gen_demo_fixtures (the same builders the round-trip capability proof
uses), so they genuinely trip the criteria being gated — a scope test against a clean file would
pass no matter what the gate did.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import remediate_office  # noqa: E402


def _scope(*allowed: str):
    """An operator scope admitting exactly `allowed`. Empty means "nothing is in scope"."""
    return lambda sc: sc in allowed


def _pdf_ok() -> bool:
    try:
        import pikepdf  # noqa: F401
        return True
    except Exception:
        return False


def _build(fmt: str, path: Path) -> None:
    import gen_demo_fixtures as gen
    getattr(gen, f"build_{fmt}")(path)


OFFICE = [("docx", "demo.docx"), ("xlsx", "demo.xlsx"), ("pptx", "demo.pptx")]


# ── the generic guard ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fmt,name", OFFICE)
def test_an_empty_scope_applies_nothing(fmt, name, tmp_path):
    """Exclude every criterion and the remediator must not touch the document.

    Deliberately not a list of criteria: this fails for ANY fix that reaches the bytes without
    consulting the scope, including one added after this test was written.
    """
    src = tmp_path / name
    _build(fmt, src)
    diffs: list = []
    out, applied, _skipped = remediate_office.remediate_office(
        src, ai_enabled=False, diffs=diffs, in_scope=_scope())

    assert applied == [], f"{fmt}: fixes applied despite an empty scope: {applied}"
    assert diffs == [], f"{fmt}: before/after records written despite an empty scope: {diffs}"
    assert out is None, f"{fmt}: a remediated file was written despite an empty scope"


@pytest.mark.parametrize("fmt,name", OFFICE)
def test_no_scope_still_remediates(fmt, name, tmp_path):
    """`in_scope=None` (no scope configured) must behave EXACTLY as before this feature.

    The regression that matters most: an unscoped deployment is the common case, and a gate that
    quietly narrows it would be a far worse bug than the one being fixed.
    """
    src = tmp_path / name
    _build(fmt, src)
    diffs: list = []
    out, applied, _skipped = remediate_office.remediate_office(
        src, ai_enabled=False, diffs=diffs, in_scope=None)

    assert applied, f"{fmt}: nothing applied with no scope set — the fixture should trip fixes"
    assert out is not None, f"{fmt}: no remediated file produced with no scope set"


@pytest.mark.parametrize("fmt,name", OFFICE)
def test_a_scope_of_one_criterion_writes_only_that_criterion(fmt, name, tmp_path):
    """Scope to 3.1.1 alone: the language fix lands, and nothing else does.

    3.1.1 is the probe because every Office format trips it (docProps/core.xml has no dc:language
    in any of the fixtures) and its fix is a single deterministic write, so "only this one ran" is
    unambiguous.
    """
    src = tmp_path / name
    _build(fmt, src)
    diffs: list = []
    _out, applied, _skipped = remediate_office.remediate_office(
        src, ai_enabled=False, diffs=diffs, in_scope=_scope("3.1.1"))

    written = {d["rule_id"] for d in diffs}
    assert written <= {"3.1.1"}, f"{fmt}: out-of-scope criteria were written: {sorted(written - {'3.1.1'})}"
    assert any("language" in a.lower() for a in applied), (
        f"{fmt}: 3.1.1 was in scope but no language fix was applied — {applied}")


@pytest.mark.parametrize("sc", ["1.3.1", "1.4.3", "2.4.2"])
def test_excluding_one_criterion_leaves_the_others_alone(sc, tmp_path):
    """The complement of the test above: exclude ONE criterion, keep the rest.

    Uses docx because its structural pass writes four different criteria (1.3.1, 1.4.3, 2.4.6,
    3.3.2) from one function — the exact shape that made a per-function gate insufficient and
    forced the gate down to each individual fix.
    """
    src = tmp_path / "demo.docx"
    _build("docx", src)
    diffs: list = []
    remediate_office.remediate_office(
        src, ai_enabled=False, diffs=diffs, in_scope=lambda c: c != sc)

    written = {d["rule_id"] for d in diffs}
    assert sc not in written, f"{sc} was excluded from the scope but was written anyway"
    assert written, "excluding one criterion suppressed everything — the gate is inverted"


# ── PDF ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _pdf_ok(), reason="pikepdf not installed")
def test_pdf_empty_scope_applies_nothing(tmp_path):
    """Same generic guard for the PDF lane, whose fixes all live in remediate_pdf itself."""
    from remediate_pdf import remediate_pdf
    src = tmp_path / "demo.pdf"
    _build("pdf", src)
    diffs: list = []
    out, applied, _skipped = remediate_pdf(
        src, ai_enabled=False, diffs=diffs, in_scope=_scope())

    assert applied == [], f"pdf: fixes applied despite an empty scope: {applied}"
    assert diffs == [], f"pdf: before/after records written despite an empty scope: {diffs}"
    assert out is None, "pdf: a remediated file was written despite an empty scope"


@pytest.mark.skipif(not _pdf_ok(), reason="pikepdf not installed")
def test_pdf_no_scope_still_remediates(tmp_path):
    """`in_scope=None` leaves the PDF lane exactly as it was."""
    from remediate_pdf import remediate_pdf
    src = tmp_path / "demo.pdf"
    _build("pdf", src)
    diffs: list = []
    out, applied, _skipped = remediate_pdf(src, ai_enabled=False, diffs=diffs, in_scope=None)

    assert applied, "pdf: nothing applied with no scope set — the fixture should trip fixes"
    assert out is not None, "pdf: no remediated file produced with no scope set"


@pytest.mark.skipif(not _pdf_ok(), reason="pikepdf not installed")
def test_pdf_contrast_pass_survives_excluding_only_the_aaa_band(tmp_path):
    """One recolour pass clears BOTH 1.4.3 (AA) and 1.4.6 (AAA).

    So excluding 1.4.6 alone must NOT switch the pass off — the AA criterion is still in scope and
    still needs fixing. Pinned because the obvious implementation (gate on each SC independently)
    silently drops the AA fix when only the AAA band is excluded.
    """
    from remediate_pdf import remediate_pdf
    src = tmp_path / "demo.pdf"
    _build("pdf", src)
    diffs: list = []
    remediate_pdf(src, ai_enabled=False, diffs=diffs, in_scope=lambda c: c != "1.4.6")

    written = {d["rule_id"] for d in diffs}
    assert "1.4.3" in written, (
        "excluding the AAA band switched off the AA contrast fix — the pass clears both, so it "
        "must still run while 1.4.3 is in scope")
    assert "1.4.6" not in written, (
        "1.4.6 was excluded but still recorded as fixed — the recolour inevitably clears it "
        "(one pass, 7:1 target), but ACP must not claim credit for an excluded criterion")
