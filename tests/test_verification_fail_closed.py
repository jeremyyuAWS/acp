"""Verification fails CLOSED: a re-scan that could not run never grants credit.

THE DEFECT THIS CLOSES. `verify_residual_scs` returned the set of WCAG SCs still failing, or
`None` when the re-scan could not run — and every caller read `None` as "credit it (never
penalise remediation on an infra hiccup)". So an unreadable document, a dead engine, a
timeout or a missing analyser all published as CLEARED.

The subtler half, and the one no caller could have defended against: a scan that RAN and
FAILED returned a set — an empty one. The residual was read off `issues` while `status` was
discarded, so "the engine reported nothing because it broke" and "the document has no
findings" were the same value. Measured on this repo before the fix:

    healthy pdf (fails 1.1.1) -> ['1.1.1', '1.4.11', '2.4.2', '3.1.1']
    truncated pdf             -> []          # status="error", credited as fully cleared

THREE OUTCOMES, TESTED SEPARATELY, as the three sections below:

  1. verified + cleared        -> credit
  2. verified + still failing  -> no credit, and the reviewer is told what still fails
  3. COULD NOT VERIFY          -> no credit, the approved value is preserved for retry

Section 3 is the new one. Sections 1 and 2 are here because a fail-closed change is only
honest if it can be shown NOT to have broken the passing case — a gate that refuses
everything is trivially "safe" and useless.

WHAT IS REAL HERE AND WHAT IS STUBBED. Sections 1-3 drive `proposals.verify_residual`
against REAL scans of REAL documents built in-test: the fixtures below are genuine PDFs
(pikepdf), and the failure modes are genuine too — a truncated file, a file whose bytes are
not the format they claim. Nothing monkeypatches the scanner to produce an error; the errors
are real ones. Section 4 is a source-level guard on the two production call sites.

PDF, NOT OFFICE, is the format under test, and that is deliberate rather than convenient.
PDF analysis runs entirely in-process (pikepdf/qpdf), so a healthy PDF grades `analysed` on
any host. Office analysis shells out to the .NET CLI, so on a host without it EVERY Office
scan grades `error` — including a perfectly healthy document. Writing section 1 against a
.docx would assert a fact about whether an engine happens to be installed, which is exactly
the environment-dependence that turned #1069's shard 3 red. See
tests/test_verification_engine_missing.py for the Office side, asserted deliberately.
"""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from proposals import Verification, verify_residual, verify_residual_scs  # noqa: E402

FILE = "report.pdf"


# ── fixtures: real PDFs, real corruption ──────────────────────────────────────
def _pdf_with_undescribed_figure(tmp_path: Path) -> bytes:
    """A tagged PDF whose figure carries no /Alt — a genuine 1.1.1 failure."""
    import pikepdf
    p = tmp_path / FILE
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    figure = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructElem, S=pikepdf.Name.Figure))
    root = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructTreeRoot, K=pikepdf.Array([figure])))
    figure.P = root
    pdf.Root.StructTreeRoot = root
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    pdf.save(p)
    return p.read_bytes()


def _described(data: bytes, tmp_path: Path) -> bytes:
    """The same PDF with /Alt written onto the figure — the criterion genuinely cleared."""
    import pikepdf
    p = tmp_path / "fixed.pdf"
    p.write_bytes(data)
    with pikepdf.open(p, allow_overwriting_input=True) as pdf:
        for el in pdf.Root.StructTreeRoot.K:
            el.Alt = pikepdf.String("A bar chart of Q3 findings, grouped by severity.")
        pdf.save(p)
    return p.read_bytes()


# ── 1. verified + cleared -> credit ───────────────────────────────────────────
def test_a_real_fix_verifies_and_may_be_credited(tmp_path):
    """The passing case still passes. Without this, a gate that refuses everything would
    look identical to a gate that works."""
    original = _pdf_with_undescribed_figure(tmp_path)
    before = verify_residual(original, FILE)
    assert before.ok, f"a healthy PDF must verify, got {before!r}"
    assert "1.1.1" in before.residual, "the fixture must actually fail 1.1.1 to be a fixture"
    assert not before.cleared({"1.1.1"}), "still failing is not cleared"

    after = verify_residual(_described(original, tmp_path), FILE)
    assert after.ok, f"the fixed PDF must verify, got {after!r}"
    assert after.cleared({"1.1.1"}), f"the fix should clear 1.1.1, got {after!r}"


# ── 2. verified + still failing -> no credit, and say what failed ─────────────
def test_a_write_that_does_not_clear_is_verified_and_refused(tmp_path):
    """The document was readable and the scan ran — so the refusal rests on evidence, and
    `still_failing` can name the criterion for the reviewer."""
    v = verify_residual(_pdf_with_undescribed_figure(tmp_path), FILE)
    assert v.ok
    assert not v.cleared({"1.1.1"})
    assert v.still_failing({"1.1.1"}) == {"1.1.1"}, (
        "a verified failure must name the criterion — this is what the reviewer is shown")


# ── 3. COULD NOT VERIFY -> no credit, whatever the residual looks like ────────
@pytest.mark.parametrize("label,make", [
    ("truncated", lambda d: d[:200]),
    ("empty", lambda d: b""),
    ("not a pdf at all", lambda d: b"this is plainly not a PDF" * 20),
])
def test_an_unverifiable_document_is_never_credited(tmp_path, label, make):
    """THE DEFECT, asserted in all three of its shapes. Each of these scans reports ZERO
    findings — so under the old code each returned an empty set and read as 'every criterion
    cleared'. The empty residual is still there; what changed is that `cleared()` refuses to
    read it as a pass."""
    broken = make(_pdf_with_undescribed_figure(tmp_path))
    v = verify_residual(broken, FILE)

    assert not v.ok, f"{label}: a scan that could not run must not report ok"
    assert v.reason, f"{label}: a refusal must say why — the reviewer is shown this"
    assert not v.cleared({"1.1.1"}), (
        f"{label}: THE REGRESSION. An unverifiable document must never be credited; "
        f"got {v!r}")
    assert not v.cleared(set()), (
        f"{label}: not even an empty criterion set may pass an unverified scan")
    assert v.still_failing({"1.1.1"}) == set(), (
        f"{label}: nothing was OBSERVED failing — 'could not verify' is not 'still failing', "
        f"and reporting it as the latter would be a different lie")


def test_the_empty_residual_of_a_broken_scan_is_not_a_pass(tmp_path):
    """Names the exact confusion the old code made, so a future reader sees why `cleared()`
    exists rather than a plain `not residual` test."""
    v = verify_residual(_pdf_with_undescribed_figure(tmp_path)[:200], FILE)
    assert v.residual == frozenset(), "the broken scan does report an empty residual"
    assert not v.ok, "...but it is not a verified empty residual"
    assert not v.cleared({"1.1.1"}), (
        "an empty residual means 'cleared' ONLY when the scan that produced it ran")


def test_a_rescan_that_raises_is_not_a_pass(monkeypatch, tmp_path):
    """The timeout / crash shape. `analyse_and_assess` raising is the re-scan failing, not
    the document passing."""
    import proposals, scanner

    def boom(*a, **k):
        raise TimeoutError("office CLI exceeded ACP_OFFICE_CLI_TIMEOUT")

    monkeypatch.setattr(scanner, "analyse_and_assess", boom)
    v = proposals.verify_residual(_pdf_with_undescribed_figure(tmp_path), FILE)
    assert not v.ok and "TimeoutError" in v.reason
    assert not v.cleared({"1.1.1"})


def test_an_unsupported_extension_verifies_nothing(tmp_path):
    """`analyse_and_assess` returns (None, None) for an extension it does not handle. That is
    'nothing was verified', not 'nothing was wrong'."""
    v = verify_residual(b"plain text", "notes.txt")
    assert not v.ok and v.reason == "no scan result"
    assert not v.cleared({"1.1.1"})


# ── the Verification value itself ─────────────────────────────────────────────
def test_cleared_is_the_only_gate_and_cannot_be_bypassed():
    """`cleared()` is the single question a credit-granting caller may ask. These cases pin
    its contract directly, so a refactor that reintroduces `not residual` fails here."""
    assert Verification(True, ()).cleared({"1.1.1"})
    assert not Verification(True, {"1.1.1"}).cleared({"1.1.1"})
    assert Verification(True, {"2.4.4"}).cleared({"1.1.1"}), "an unrelated SC does not block"
    assert not Verification(False, ()).cleared({"1.1.1"}), "could-not-verify is never a pass"
    assert not Verification(False, ()).cleared(set()), "not even for no criteria at all"


def test_verification_is_immutable():
    """A caller must not be able to launder a failed verification into a pass by assignment."""
    v = Verification(False, (), "scan status 'error'")
    with pytest.raises(AttributeError):
        v.ok = True


# ── 4. neither production caller may go back to the fail-open shim ────────────
def _assignments_to(fn_src: str, name: str) -> list[str]:
    """Every expression assigned to `name` inside the given source."""
    tree = ast.parse(fn_src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    out.append(ast.unparse(node.value))
    return out


def test_both_credit_granting_callers_use_the_three_state_result():
    """THE GUARD. `verify_residual_scs` still exists — ~15 observational tests and several
    detector docstrings use it to ask what a scan reports, which is a fair question. But a
    credit-granting caller reaching for it reintroduces the defect silently, because its
    `None` reads as falsey and its empty set reads as cleared.

    Both production call sites live in api/handlers.py: the auto-fix loop (`_remediate_file`)
    and the approved-value lane (`_apply_one_value_kind`). This asserts neither calls the
    observational shim, and that the fail-open comparisons they used to make are gone."""
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    tree = ast.parse(src)

    for fname in ("_remediate_file", "_apply_one_value_kind"):
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fname),
                  None)
        assert fn is not None, f"{fname} not found — this guard needs updating with the rename"
        body = ast.unparse(fn)
        assert "_verify_residual_scs" not in body, (
            f"{fname} calls the OBSERVATIONAL shim. It cannot distinguish 'cleared' from "
            f"'could not verify' — use _verify_residual and Verification.cleared().")
        assert "_verify_residual" in body, f"{fname} must verify before crediting"
        # the two fail-open comparisons this change removed
        for banned in ("residual is None", "residual is not None"):
            assert banned not in body, (
                f"{fname} still tests `{banned}` — that is the fail-open read: it treats a "
                f"re-scan that could not run as a pass.")


def test_the_observational_shim_is_documented_as_unsafe_for_credit():
    """It stays available, so its docstring is the thing standing between a future caller and
    the same defect. Assert the warning is actually there."""
    doc = verify_residual_scs.__doc__ or ""
    assert "DO NOT USE THIS TO GRANT CREDIT" in doc
    assert "verify_residual" in doc, "it must point at the safe alternative"
